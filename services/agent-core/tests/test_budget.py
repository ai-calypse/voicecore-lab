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


def test_reserve_all_is_all_or_nothing_when_a_later_one_is_refused(tmp_path):
    path = ledger_with(tmp_path, [{"pool": "usd", "amount": 4.95}])
    with pytest.raises(budget.BudgetExceeded):  # STT 0.0385 fits (4.9885), then LLM 0.02 would reach 5.0085
        budget.reserve_all([("usd", 0.0385, "server stt s-1"), ("usd", 0.02, "server llm s-1")], ledger_path=path)
    assert json.loads(path.read_text())["entries"] == [{"pool": "usd", "amount": 4.95}]  # atomic: nothing was written
    assert budget.total("usd", ledger_path=path) == 4.95


def test_reserve_all_unknown_pool_writes_nothing(tmp_path):
    path = ledger_with(tmp_path, [])
    with pytest.raises(KeyError):
        budget.reserve_all([("usd", 0.01, "a"), ("nope", 1, "b")], ledger_path=path)
    assert json.loads(path.read_text())["entries"] == []


def test_orphans_reports_reserved_older_than_1h_or_without_ts(tmp_path, monkeypatch):
    monkeypatch.setattr(budget, "now", lambda: 10_000.0)
    path = ledger_with(tmp_path, [
        {"id": "a", "pool": "usd", "amount": 0.1, "status": "reserved", "ts": 10_000 - 7200},  # 2 h old
        {"id": "b", "pool": "usd", "amount": 0.1, "status": "reserved", "ts": 10_000 - 600},   # 10 min old: in use
        {"id": "c", "pool": "usd", "amount": 0.1, "status": "reserved"},                       # before entries had ts
        {"id": "d", "pool": "usd", "amount": 0.1, "status": "settled", "ts": 0},
    ])
    assert [e["id"] for e in budget.orphans(ledger_path=path)] == ["a", "c"]
