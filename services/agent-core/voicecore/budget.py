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
LEDGER = Path(__file__).resolve().parents[3] / "benchmarks/spend_ledger.json"  # default; VOICECORE_LEDGER overrides
now = time.time  # wall clock for entry timestamps (daily caps); tests replace it


def ledger_file(ledger_path=None) -> Path:
    """Resolved per call, so a test (or a server flag) that sets VOICECORE_LEDGER after import is honoured."""
    return Path(ledger_path or os.environ.get("VOICECORE_LEDGER") or LEDGER)


class BudgetExceeded(Exception):
    pass


@dataclass(frozen=True)
class Reservation:
    id: str
    pool: str
    amount: float
    label: str


def _sum(entries, pool):
    # Entries written before pools existed are USD estimates in `estimated_usd`.
    return round(sum(e.get("amount", e.get("estimated_usd", 0.0)) for e in entries if e.get("pool", "usd") == pool), 6)


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
        data["totals"] = {pool: _sum(data["entries"], pool) for pool in CAPS}
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
    return _sum(_entries(ledger_file(ledger_path)), pool)


def reserve(pool, amount, label="", ledger_path=None):
    with _locked(ledger_file(ledger_path)) as data:
        spent = _sum(data["entries"], pool)
        if round(spent + amount, 6) > CAPS[pool]:
            raise BudgetExceeded(f"{pool}: {spent} spent + {amount} requested > cap {CAPS[pool]}")
        r = Reservation(uuid.uuid4().hex[:12], pool, amount, label)
        data["entries"].append({"id": r.id, "pool": pool, "amount": amount, "label": label, "status": "reserved", "ts": now()})
    return r


def settle(reservation, actual, ledger_path=None, **meta):
    with _locked(ledger_file(ledger_path)) as data:
        for e in data["entries"]:
            if e.get("id") == reservation.id:
                e.update(amount=round(actual, 6), reserved=reservation.amount, status="settled", **meta)
                return
        raise KeyError(f"reservation {reservation.id} not in ledger")


def reserve_all(specs, ledger_path=None) -> list[Reservation]:
    """Reserve several (pool, amount, label) atomically under one ledger lock: all are written, or none (an over-cap
    or unknown pool raises before anything is written, so no partial reservation ever counts against a cap)."""
    with _locked(ledger_file(ledger_path)) as data:
        spent, out = {}, []
        for pool, amount, label in specs:
            spent.setdefault(pool, _sum(data["entries"], pool))
            if round(spent[pool] + amount, 6) > CAPS[pool]:
                raise BudgetExceeded(f"{pool}: {spent[pool]} spent + {amount} requested > cap {CAPS[pool]}")
            spent[pool] = round(spent[pool] + amount, 6)
            out.append(Reservation(uuid.uuid4().hex[:12], pool, amount, label))
        for r in out:
            data["entries"].append({"id": r.id, "pool": r.pool, "amount": r.amount, "label": r.label, "status": "reserved", "ts": now()})
    return out


def orphans(older_than_s: float = 3600, ledger_path=None) -> list[dict]:
    """Reservations still 'reserved' after older_than_s (or from before entries had a ts). Report only: they already
    count at their full amount, the safe side; settling them by guessing could under-count real spend."""
    entries = _entries(ledger_file(ledger_path))
    cutoff = now() - older_than_s
    return [e for e in entries if e.get("status") == "reserved" and e.get("ts", 0) < cutoff]


if __name__ == "__main__":  # python -m voicecore.budget orphans
    import sys

    if sys.argv[1:] == ["orphans"]:
        found = orphans()
        for e in found:
            print(f"{e.get('id')}  {e.get('pool')}  {e.get('amount')}  {e.get('label', '')}")
        print(f"{len(found)} orphaned reservation(s), {round(sum(e.get('amount', 0) for e in found), 6)} counted at full amount")
    else:
        sys.exit("usage: python -m voicecore.budget orphans")
