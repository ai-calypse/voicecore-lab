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


def test_total_waits_for_a_writer_instead_of_reading_a_half_written_ledger():
    import fcntl
    import threading

    budget.settle(budget.reserve("usd", 1.0, "t"), 0.5)
    path, got = budget.ledger_file(), []
    with open(path, "r+") as f:
        fcntl.flock(f, fcntl.LOCK_EX)  # a writer mid-rewrite: the file is truncated
        text = f.read()
        f.seek(0)
        f.truncate()
        reader = threading.Thread(target=lambda: got.append(budget.total("usd")))
        reader.start()
        reader.join(0.2)
        assert reader.is_alive()  # blocked on the lock, not reading an empty file
        f.write(text)
        f.flush()
        fcntl.flock(f, fcntl.LOCK_UN)
    reader.join(2)
    assert got == [0.5]


def test_public_counts_in_usd_and_public():
    budget.reserve("usd", 0.10, "a public session", sub="public")
    assert (budget.total("usd"), budget.total("public")) == (0.10, 0.10)


def test_public_daily_cap(monkeypatch):
    day = 1_793_318_400.0  # 2026-10-30 00:00 UTC
    monkeypatch.setattr(budget, "now", lambda: day + 3600)
    budget.reserve("usd", 0.45, "s1", sub="public")
    with pytest.raises(budget.DailyCapReached):
        budget.reserve("usd", 0.10, "s2", sub="public")  # 0.55 > the 0.50 daily public cap
    budget.reserve("usd", 0.10, "a private session")  # the usd pool itself is not limited per day
    monkeypatch.setattr(budget, "now", lambda: day + 86_400 + 60)  # the next UTC day
    budget.reserve("usd", 0.10, "s3", sub="public")
    assert budget.total("public") == 0.55


def test_public_total_cap_holds_across_days(monkeypatch):
    day = 1_793_318_400.0
    for d in range(4):
        monkeypatch.setattr(budget, "now", lambda d=d: day + d * 86_400)
        budget.reserve("usd", 0.50, f"day {d}", sub="public")
    monkeypatch.setattr(budget, "now", lambda: day + 4 * 86_400)
    with pytest.raises(budget.BudgetExceeded):
        budget.reserve("usd", 0.01, "day 4", sub="public")  # 2.00 is the public total


def test_a_sub_cap_counts_only_reservations_in_its_own_pool():
    r = budget.reserve("cartesia_credits", 1500, "cartesia tts", sub="public")  # credits are not dollars
    assert (budget.total("cartesia_credits"), budget.total("public")) == (1500, 0.0)
    budget.settle(r, 0)


def test_caps_from_env():
    """A self-hosted install sets its own caps (Step 10); unset, the project's own caps stay."""
    import subprocess
    import sys

    def cap(env):
        code = "from voicecore import budget; print(budget.CAPS['usd'], budget.SUBCAPS['public']['daily'], budget.SUBCAPS['public']['total'])"
        return subprocess.run([sys.executable, "-c", code], env={**__import__("os").environ, **env}, capture_output=True,
                              text=True, check=True).stdout.split()

    assert cap({"VOICECORE_CAP_USD": "20"})[0] == "20.0"
    assert cap({})[:3] == ["5.0", "0.5", "2.0"]
    assert cap({"VOICECORE_PUBLIC_DAILY": "1", "VOICECORE_PUBLIC_TOTAL": "10"})[1:] == ["1.0", "10.0"]


def test_dashboard_limits_replace_the_environments(tmp_path, monkeypatch):
    """Limits saved on the dashboard's Voice page (VOICECORE_LIMITS_FILE) apply from the next reservation, no restart."""
    path, limits = ledger_with(tmp_path, []), tmp_path / "limits.json"
    monkeypatch.setenv("VOICECORE_LIMITS_FILE", str(limits))
    limits.write_text(json.dumps({"daily_usd": 0.3, "total_usd": 8}))
    budget.reserve("usd", 0.25, "a", ledger_path=path, sub="public")
    with pytest.raises(budget.DailyCapReached):
        budget.reserve("usd", 0.10, "b", ledger_path=path, sub="public")
    assert budget.limits() == {"cap_usd": 8.0, "daily_cap_usd": 0.3}
    budget.reserve("usd", 5.5, "c", ledger_path=path)  # the total also raises the pool's own $5 cap
    limits.unlink()
    budget.apply_limits()
    assert budget.limits() == {"cap_usd": 2.0, "daily_cap_usd": 0.5}  # back to the environment's
