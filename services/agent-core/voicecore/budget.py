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


def total(pool, ledger_path=None):
    path = ledger_file(ledger_path)
    return _sum(json.loads(path.read_text()).get("entries", []) if path.exists() else [], pool)


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
    """Reserve several (pool, amount, label) in order, all or nothing: if one is refused, the ones already made are
    settled at 0 (nothing was used) and BudgetExceeded is raised, so no reservation is left counting forever."""
    done = []
    try:
        for pool, amount, label in specs:
            done.append(reserve(pool, amount, label, ledger_path=ledger_path))
    except BudgetExceeded:
        for r in done:
            settle(r, 0, ledger_path=ledger_path, refused_with_session=True)
        raise
    return done
