import json

import pytest

from voicecore import budget


def ledger_with(tmp_path, entries):
    path = tmp_path / "spend_ledger.json"
    path.write_text(json.dumps({"entries": entries}))
    return path


def test_usd_reservation_over_the_5_dollar_cap_is_refused(tmp_path):
    path = ledger_with(tmp_path, [{"pool": "usd", "amount": 4.95}])
    with pytest.raises(budget.BudgetExceeded):
        budget.reserve("usd", 0.10, ledger_path=path)


def test_credit_reservation_over_16000_is_refused(tmp_path):
    path = ledger_with(tmp_path, [{"pool": "cartesia_credits", "amount": 15900}])
    with pytest.raises(budget.BudgetExceeded):
        budget.reserve("cartesia_credits", 200, ledger_path=path)


def test_credit_entries_do_not_change_the_usd_total(tmp_path):
    path = ledger_with(tmp_path, [{"pool": "usd", "amount": 0.525}, {"pool": "cartesia_credits", "amount": 500}])
    assert budget.total("usd", ledger_path=path) == 0.525


def test_old_entries_without_pool_count_as_usd(tmp_path):
    old = [{"run_id": "r", "session": i, "connected_seconds": 30.0, "estimated_usd": 0.075} for i in range(7)]
    path = ledger_with(tmp_path, old)
    assert budget.total("usd", ledger_path=path) == 0.525


def test_an_unsettled_reservation_counts_against_the_cap(tmp_path):
    path = ledger_with(tmp_path, [])
    budget.reserve("usd", 0.10, ledger_path=path)
    assert budget.total("usd", ledger_path=path) == 0.10


def test_settle_replaces_the_reservation_with_the_actual_amount(tmp_path):
    path = ledger_with(tmp_path, [{"pool": "usd", "amount": 1.0}])
    r = budget.reserve("usd", 0.10, label="smoke", ledger_path=path)
    budget.settle(r, 0.03, ledger_path=path)
    assert budget.total("usd", ledger_path=path) == 1.03


# Step 09 (S09-T00): tests must never write the real ledger, and entries carry a wall-clock time

def test_ledger_path_is_resolved_at_call_time(tmp_path, monkeypatch):
    path = tmp_path / "late.json"
    monkeypatch.setenv("VOICECORE_LEDGER", str(path))  # set after the module was imported
    budget.reserve("usd", 0.01, label="late")
    assert json.loads(path.read_text())["entries"][0]["label"] == "late"


def test_reserve_writes_wall_clock_ts(tmp_path, monkeypatch):
    monkeypatch.setattr(budget, "now", lambda: 1_761_800_000.0)
    path = ledger_with(tmp_path, [])
    budget.reserve("usd", 0.01, ledger_path=path)
    assert json.loads(path.read_text())["entries"][0]["ts"] == 1761800000.0
