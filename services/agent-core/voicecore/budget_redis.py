"""The budget ledger in Redis, for several orchestrator copies (Step 09 Phase 10). VOICECORE_LEDGER=redis://... selects it.

Same contract as the file ledger in budget.py. Amounts are integer micro-units. One Lua script checks every cap and
writes every reservation atomically, so copies can never jointly pass a cap. The store refuses to work until
`python -m voicecore.budget migrate` has seeded it from the file ledger: an empty Redis must never mean "nothing spent".
Redis unreachable means BudgetUnavailable: new sessions are refused, never let through (fail closed).
"""
import json
import time

import redis

from voicecore import budget

PREFIX = "vc:budget:"
M = 1_000_000  # micro-units per unit

RESERVE = """
local p = ARGV[1]
if redis.call('EXISTS', p .. 'seeded') == 0 then return redis.error_reply('UNSEEDED ledger not seeded') end
local ts, day, sub = ARGV[2], ARGV[3], ARGV[4]
local subcap, daycap, n = tonumber(ARGV[5]), tonumber(ARGV[6]), tonumber(ARGV[7])
local spent = {}
local function get(k) if spent[k] == nil then spent[k] = tonumber(redis.call('GET', k) or '0') end return spent[k] end
for i = 0, n - 1 do
  local b = 8 + i * 6
  local pool, amt, cap, applies = ARGV[b + 1], tonumber(ARGV[b + 2]), tonumber(ARGV[b + 3]), ARGV[b + 5]
  local checks = {{p .. 'total:' .. pool, cap, 'CAP'}}
  if applies == '1' then
    table.insert(checks, {p .. 'sub:' .. sub, subcap, 'CAP'})
    table.insert(checks, {p .. 'sub:' .. sub .. ':' .. day, daycap, 'DAILY'})
  end
  for _, c in ipairs(checks) do
    local v = get(c[1])
    if v + amt > c[2] then return redis.error_reply(c[3] .. ' ' .. c[1] .. ': ' .. v .. ' spent + ' .. amt .. ' > cap ' .. c[2]) end
  end
  for _, c in ipairs(checks) do spent[c[1]] = spent[c[1]] + amt end
end
for k, v in pairs(spent) do redis.call('SET', k, v) end
for i = 0, n - 1 do
  local b = 8 + i * 6
  local id = ARGV[b]
  local s = ''
  if ARGV[b + 5] == '1' then s = sub end
  redis.call('HSET', p .. 'entry:' .. id, 'pool', ARGV[b + 1], 'amount', ARGV[b + 2], 'label', ARGV[b + 4],
             'status', 'reserved', 'ts', ts, 'sub', s, 'day', day)
  redis.call('ZADD', p .. 'reserved', ts, id)
end
return 'OK'
"""

SETTLE = """
local p, id, actual = ARGV[1], ARGV[2], tonumber(ARGV[3])
local e = p .. 'entry:' .. id
if redis.call('EXISTS', e) == 0 then return redis.error_reply('NOENTRY reservation ' .. id .. ' not in ledger') end
local amt = tonumber(redis.call('HGET', e, 'amount'))
local pool, sub, day = redis.call('HGET', e, 'pool'), redis.call('HGET', e, 'sub'), redis.call('HGET', e, 'day')
local delta = actual - amt
redis.call('INCRBY', p .. 'total:' .. pool, delta)
if sub ~= '' then
  redis.call('INCRBY', p .. 'sub:' .. sub, delta)
  redis.call('INCRBY', p .. 'sub:' .. sub .. ':' .. day, delta)  -- the day it was reserved on, as the file ledger counts it
end
redis.call('HSET', e, 'amount', actual, 'reserved', amt, 'status', 'settled', 'meta', ARGV[4])
redis.call('ZREM', p .. 'reserved', id)
return 'OK'
"""

MIGRATE = """
local p = ARGV[1]
if redis.call('EXISTS', p .. 'seeded') == 1 then return redis.error_reply('SEEDED already seeded') end
for i = 3, #ARGV, 2 do redis.call('SET', p .. ARGV[i], ARGV[i + 1]) end
redis.call('SET', p .. 'seeded', ARGV[2])
return 'OK'
"""

_clients: dict[str, tuple] = {}
_down_until: dict[str, float] = {}  # after a failed connection, fail fast for a while: callers run on the event loop
DOWN_FOR_S = 5.0


def _store(url: str):
    if url not in _clients:
        r = redis.Redis.from_url(url, socket_timeout=1, socket_connect_timeout=1, decode_responses=True)
        _clients[url] = (r, r.register_script(RESERVE), r.register_script(SETTLE))
    return _clients[url]


def _run(fn, url=None):
    if url and time.monotonic() < _down_until.get(url, 0):
        raise budget.BudgetUnavailable("ledger unreachable (failed moments ago)")
    try:
        return fn()
    except redis.exceptions.ResponseError as e:
        msg = str(e)
        if msg.startswith("UNSEEDED"):
            raise budget.BudgetUnavailable("ledger not seeded: run python -m voicecore.budget migrate first") from None
        if msg.startswith("DAILY"):
            raise budget.DailyCapReached(msg) from None
        if msg.startswith("CAP"):
            raise budget.BudgetExceeded(msg) from None
        if msg.startswith("NOENTRY"):
            raise KeyError(msg) from None
        if msg.startswith("SEEDED"):
            raise budget.BudgetUnavailable("already seeded; migrating twice would count the old spend twice") from None
        raise budget.BudgetUnavailable(f"ledger refused the write: {msg[:80]}") from None  # e.g. OOM, a read-only replica
    except redis.exceptions.RedisError as e:  # down, timed out: refuse new spend
        if url and isinstance(e, (redis.exceptions.ConnectionError, redis.exceptions.TimeoutError)):
            _down_until[url] = time.monotonic() + DOWN_FOR_S
        raise budget.BudgetUnavailable(f"ledger unreachable: {type(e).__name__}") from None


def reserve_all(specs, url: str, sub=None) -> list:
    _, script, _ = _store(url)
    ts = budget.now()
    out, args = [], []
    for pool, amount, label in specs:
        r = budget.Reservation(budget.uuid.uuid4().hex[:12], pool, amount, label)
        applies = sub is not None and budget.SUBCAPS[sub]["pool"] == pool
        args += [r.id, pool, round(amount * M), round(budget.CAPS[pool] * M), label, "1" if applies else "0"]
        out.append(r)
    caps = budget.SUBCAPS.get(sub, {"total": 0, "daily": 0})
    _run(lambda: script(args=[PREFIX, ts, int(ts // 86_400), sub or "", round(caps["total"] * M), round(caps["daily"] * M),
                              len(out), *args]), url)
    return out


def settle(reservation, actual, url: str, **meta):
    _, _, script = _store(url)
    _run(lambda: script(args=[PREFIX, reservation.id, round(actual * M), json.dumps(meta)]), url)


def total(pool, url: str) -> float:
    r, _, _ = _store(url)
    key = f"{PREFIX}sub:{pool}" if pool in budget.SUBCAPS else f"{PREFIX}total:{pool}"
    return round(int(_run(lambda: r.get(key), url) or 0) / M, 6)


def orphans(older_than_s: float, url: str) -> list[dict]:
    r, _, _ = _store(url)
    ids = _run(lambda: r.zrangebyscore(f"{PREFIX}reserved", "-inf", budget.now() - older_than_s))
    entries = [{**_run(lambda i=i: r.hgetall(f"{PREFIX}entry:{i}")), "id": i} for i in ids]
    return [{**e, "amount": int(e["amount"]) / M, "ts": float(e["ts"])} for e in entries]


def migrate(file_path: str, url: str) -> dict:
    """Seed Redis with the file ledger's totals (reserved entries count in full, as they do in the file)."""
    r, _, _ = _store(url)
    if not budget.Path(file_path).exists():  # a typo must never seed 0 spent
        raise FileNotFoundError(file_path)
    entries = budget._entries(budget.Path(file_path))
    keys = {f"{PREFIX}total:{pool}": budget._sum(entries, pool) for pool in budget.CAPS}
    for sub in budget.SUBCAPS:
        keys[f"{PREFIX}sub:{sub}"] = budget._sum(entries, sub)
        for day in {int(e.get("ts", 0) // 86_400) for e in entries if e.get("sub") == sub}:
            keys[f"{PREFIX}sub:{sub}:{day}"] = budget._sum(entries, sub, day=day)
    pairs = [x for k, v in keys.items() for x in (k.removeprefix(PREFIX), round(v * M))]
    _run(lambda: r.register_script(MIGRATE)(args=[PREFIX, file_path, *pairs]))  # all at once, or nothing if seeded
    return {k.removeprefix(PREFIX): v for k, v in keys.items()}
