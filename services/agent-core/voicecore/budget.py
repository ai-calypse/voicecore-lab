"""Spend guard for live providers: every paid call reserves from a pool first.

Pools and caps (user decision 2026-10-29): `usd` covers Deepgram + OpenRouter,
$5.00 total for the whole project; `cartesia_credits` allows at most 16,000 of
the 20,000 credits owned. A reservation is written to the ledger immediately,
so a crash before settle() still counts the worst case against the cap.
"""
import fcntl
import json
import os
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

CAPS = {"usd": 5.00, "cartesia_credits": 16000}
# Sub-caps inside a pool (Step 09 Phase 9): what a public deployment may spend, checked under the same lock as the pool.
SUBCAPS = {"public": {"pool": "usd", "total": 2.00, "daily": 0.50}}
LEDGER = Path(__file__).resolve().parents[3] / "benchmarks/spend_ledger.json"  # default; VOICECORE_LEDGER overrides
now = time.time  # wall clock for entry timestamps (daily caps); tests replace it


def ledger_file(ledger_path=None) -> Path:
    """Resolved per call, so a test (or a server flag) that sets VOICECORE_LEDGER after import is honoured."""
    return Path(ledger_path or os.environ.get("VOICECORE_LEDGER") or LEDGER)


class BudgetExceeded(Exception):
    pass


class DailyCapReached(BudgetExceeded):
    """Today's share is used up; tomorrow (UTC) there is more."""


class BudgetUnavailable(BudgetExceeded):
    """The ledger cannot be checked (Redis down, or never seeded): no new spend, never a guess."""


def _redis_url(ledger_path=None) -> str | None:
    url = str(ledger_path or os.environ.get("VOICECORE_LEDGER") or "")
    return url if url.startswith(("redis://", "rediss://")) else None


@dataclass(frozen=True)
class Reservation:
    id: str
    pool: str
    amount: float
    label: str


def _sum(entries, pool, day=None):
    """A pool's total, or a sub-cap's (entries tagged with it), or a sub-cap's total for one UTC day."""
    # Entries written before pools existed are USD estimates in `estimated_usd`.
    match = (lambda e: e.get("sub") == pool) if pool in SUBCAPS else (lambda e: e.get("pool", "usd") == pool)
    return round(sum(e.get("amount", e.get("estimated_usd", 0.0)) for e in entries
                     if match(e) and (day is None or int(e.get("ts", 0) // 86_400) == day)), 6)


def _check(entries, pool, amount, sub, spent):
    """Raise unless amount fits the pool and, with sub, the sub-cap's total and today's share. spent: running totals.
    A sub-cap counts only reservations in its own pool (the public dollars never count Cartesia credits)."""
    if sub is not None and SUBCAPS[sub]["pool"] != pool:
        sub = None
    for key, cap, exc in [(pool, CAPS[pool], BudgetExceeded)] + ([] if sub is None else [
            (sub, SUBCAPS[sub]["total"], BudgetExceeded), ((sub, "today"), SUBCAPS[sub]["daily"], DailyCapReached)]):
        if key not in spent:
            spent[key] = _sum(entries, sub, day=int(now() // 86_400)) if isinstance(key, tuple) else _sum(entries, key)
        if round(spent[key] + amount, 6) > cap:
            raise exc(f"{key}: {spent[key]} spent + {amount} requested > cap {cap}")
    for key in [pool] + ([] if sub is None else [sub, (sub, "today")]):
        spent[key] = round(spent[key] + amount, 6)


@contextmanager
def _locked(path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with os.fdopen(os.open(path, os.O_RDWR | os.O_CREAT), "r+") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        text = f.read()
        data = json.loads(text) if text.strip() else {}
        data.setdefault("entries", [])
        yield data
        data.pop("budget_usd", None)  # single-pool fields from the S00-T02 ledger
        data.pop("total_estimated_usd", None)
        data["caps"] = CAPS
        data["totals"] = {pool: _sum(data["entries"], pool) for pool in [*CAPS, *SUBCAPS]}
        f.seek(0)
        f.truncate()
        f.write(json.dumps(data, indent=2) + "\n")


def _entries(path) -> list[dict]:
    """Read under a shared lock: writers truncate and rewrite the file under an exclusive one."""
    if not path.exists():
        return []
    with open(path) as f:
        fcntl.flock(f, fcntl.LOCK_SH)
        text = f.read()
    return json.loads(text).get("entries", []) if text.strip() else []


def total(pool, ledger_path=None):
    if url := _redis_url(ledger_path):
        from voicecore import budget_redis
        return budget_redis.total(pool, url)
    return _sum(_entries(ledger_file(ledger_path)), pool)


def reserve(pool, amount, label="", ledger_path=None, sub=None):
    """sub: a sub-cap inside the pool (e.g. "public"); the entry counts against both."""
    return reserve_all([(pool, amount, label)], ledger_path, sub=sub)[0]


def settle(reservation, actual, ledger_path=None, **meta):
    if url := _redis_url(ledger_path):
        from voicecore import budget_redis
        return budget_redis.settle(reservation, actual, url, **meta)
    with _locked(ledger_file(ledger_path)) as data:
        for e in data["entries"]:
            if e.get("id") == reservation.id:
                e.update(amount=round(actual, 6), reserved=reservation.amount, status="settled", **meta)
                return
        raise KeyError(f"reservation {reservation.id} not in ledger")


def reserve_all(specs, ledger_path=None, sub=None) -> list[Reservation]:
    """Reserve several (pool, amount, label) atomically under one ledger lock: all are written, or none (an over-cap
    or unknown pool raises before anything is written, so no partial reservation ever counts against a cap).
    sub: a sub-cap (e.g. "public") every one of them also counts against, in total and for today (UTC)."""
    if url := _redis_url(ledger_path):
        from voicecore import budget_redis
        return budget_redis.reserve_all(specs, url, sub)
    with _locked(ledger_file(ledger_path)) as data:
        spent, out = {}, []
        for pool, amount, label in specs:
            _check(data["entries"], pool, amount, sub, spent)
            out.append(Reservation(uuid.uuid4().hex[:12], pool, amount, label))
        for r in out:
            tag = {"sub": sub} if sub and SUBCAPS[sub]["pool"] == r.pool else {}
            data["entries"].append({"id": r.id, "pool": r.pool, "amount": r.amount, "label": r.label, "status": "reserved", "ts": now(), **tag})
    return out


def orphans(older_than_s: float = 3600, ledger_path=None) -> list[dict]:
    """Reservations still 'reserved' after older_than_s (or from before entries had a ts). Report only: they already
    count at their full amount, the safe side; settling them by guessing could under-count real spend."""
    if url := _redis_url(ledger_path):
        from voicecore import budget_redis
        return budget_redis.orphans(older_than_s, url)
    entries = _entries(ledger_file(ledger_path))
    cutoff = now() - older_than_s
    return [e for e in entries if e.get("status") == "reserved" and e.get("ts", 0) < cutoff]


def migrate(file_path, url) -> dict:
    """Seed a Redis ledger with a file ledger's totals, once, before any orchestrator uses it."""
    from voicecore import budget_redis
    return budget_redis.migrate(str(file_path), url)


if __name__ == "__main__":  # python -m voicecore.budget orphans | migrate --from FILE --to redis://...
    import sys

    if sys.argv[1:2] == ["migrate"] and len(sys.argv) == 6 and sys.argv[2] == "--from" and sys.argv[4] == "--to":
        try:
            for key, value in migrate(sys.argv[3], sys.argv[5]).items():
                print(f"{key} = {value}")
        except __import__("voicecore.budget").budget.BudgetUnavailable as e:  # the module's class: as __main__ this file is a copy
            if "already seeded" not in str(e):
                raise
            print("already seeded; nothing to do")  # a restarted stack must not count the old spend twice
    elif sys.argv[1:] == ["orphans"]:
        found = orphans()
        for e in found:
            print(f"{e.get('id')}  {e.get('pool')}  {e.get('amount')}  {e.get('label', '')}")
        print(f"{len(found)} orphaned reservation(s), {round(sum(e.get('amount', 0) for e in found), 6)} counted at full amount")
    else:
        sys.exit("usage: python -m voicecore.budget orphans | migrate --from FILE --to redis://HOST:PORT/DB")
