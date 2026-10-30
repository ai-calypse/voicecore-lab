"""Seam 18: the budget ledger contract, for the file store and the Redis store (Step 09 Phase 10).

Redis cases need VOICECORE_TEST_REDIS (e.g. redis://127.0.0.1:16379/15; its database is flushed) and skip without it.
"""
import json
import os
from concurrent.futures import ProcessPoolExecutor

import pytest

from voicecore import budget

REDIS = os.environ.get("VOICECORE_TEST_REDIS")


@pytest.fixture(params=["file", "redis"])
def ledger(request, tmp_path, monkeypatch):
    if request.param == "file":
        yield str(tmp_path / "ledger.json")
        return
    if not REDIS:
        pytest.skip("no VOICECORE_TEST_REDIS")
    import redis

    redis.Redis.from_url(REDIS).flushdb()
    (tmp_path / "empty.json").write_text('{"entries": []}')
    budget.migrate(str(tmp_path / "empty.json"), REDIS)  # an empty file ledger: seeded at 0
    yield REDIS


def worker(ledger: str) -> bool:
    try:
        budget.reserve("usd", 0.01, "race", ledger_path=ledger)
        return True
    except budget.BudgetExceeded:
        return False


def test_reserve_settle_total(ledger):
    r = budget.reserve("usd", 0.10, "s", ledger_path=ledger)
    assert budget.total("usd", ledger) == 0.10
    budget.settle(r, 0.04, ledger)
    assert budget.total("usd", ledger) == 0.04


def test_public_daily_cap(ledger, monkeypatch):
    day = 1_793_318_400.0
    monkeypatch.setattr(budget, "now", lambda: day + 3600)
    budget.reserve("usd", 0.45, "s1", ledger, sub="public")
    with pytest.raises(budget.DailyCapReached):
        budget.reserve("usd", 0.10, "s2", ledger, sub="public")
    monkeypatch.setattr(budget, "now", lambda: day + 86_400 + 60)
    budget.reserve("usd", 0.10, "s3", ledger, sub="public")
    assert (budget.total("public", ledger), budget.total("usd", ledger)) == (0.55, 0.55)


def test_settle_lowers_the_public_day_it_was_reserved_on(ledger, monkeypatch):
    day = 1_793_318_400.0
    monkeypatch.setattr(budget, "now", lambda: day + 3600)
    r = budget.reserve("usd", 0.45, "s1", ledger, sub="public")
    budget.settle(r, 0.05, ledger)  # the session used little: today's share has room again
    budget.reserve("usd", 0.40, "s2", ledger, sub="public")
    assert budget.total("public", ledger) == 0.45


def test_orphans(ledger, monkeypatch):
    monkeypatch.setattr(budget, "now", lambda: 10_000.0)
    budget.reserve("usd", 0.01, "old", ledger)
    monkeypatch.setattr(budget, "now", lambda: 10_000.0 + 7200)
    budget.reserve("usd", 0.01, "new", ledger)
    assert [e["label"] for e in budget.orphans(3600, ledger)] == ["old"]


def test_concurrent_reserves_never_exceed_cap(ledger):
    budget.settle(budget.reserve("usd", 4.50, "earlier spend", ledger_path=ledger), 4.50, ledger)
    with ProcessPoolExecutor(8) as pool:  # processes, not tasks: reserve() is synchronous, so tasks would never race
        won = sum(pool.map(worker, [ledger] * 100))
    assert (won, budget.total("usd", ledger)) == (50, 5.0)


def test_redis_store_refuses_unseeded():
    if not REDIS:
        pytest.skip("no VOICECORE_TEST_REDIS")
    import redis

    redis.Redis.from_url(REDIS).flushdb()
    with pytest.raises(budget.BudgetUnavailable, match="not seeded"):
        budget.reserve("usd", 0.01, "s", ledger_path=REDIS)


def test_migrate_carries_the_file_totals(tmp_path):
    if not REDIS:
        pytest.skip("no VOICECORE_TEST_REDIS")
    import redis

    redis.Redis.from_url(REDIS).flushdb()
    path = str(tmp_path / "old.json")
    budget.settle(budget.reserve("usd", 1.25, "spent", ledger_path=path), 1.25, path)
    budget.reserve("usd", 0.10, "still reserved", ledger_path=path, sub="public")
    budget.migrate(path, REDIS)
    assert (budget.total("usd", REDIS), budget.total("public", REDIS)) == (1.35, 0.10)
    assert json.loads(open(path).read())["totals"]["usd"] == 1.35


def test_redis_down_fails_closed():
    with pytest.raises(budget.BudgetUnavailable):
        budget.reserve("usd", 0.01, "s", ledger_path="redis://127.0.0.1:1/0")  # nothing listens there


def test_migrate_refuses_a_missing_file(tmp_path):
    if not REDIS:
        pytest.skip("no VOICECORE_TEST_REDIS")
    import redis

    redis.Redis.from_url(REDIS).flushdb()
    with pytest.raises(FileNotFoundError):
        budget.migrate(str(tmp_path / "typo.json"), REDIS)  # seeding 0 from a typo would hand out the whole cap again
    with pytest.raises(budget.BudgetUnavailable, match="not seeded"):
        budget.reserve("usd", 0.01, "s", ledger_path=REDIS)


def test_any_other_redis_error_is_unavailable(monkeypatch):
    import redis

    from voicecore import budget_redis

    def readonly():
        raise redis.exceptions.ResponseError("READONLY You can't write against a read only replica.")

    with pytest.raises(budget.BudgetUnavailable):
        budget_redis._run(readonly)


def test_a_down_ledger_fails_fast_after_the_first_try():
    """The orchestrator calls the ledger on its event loop: a dead Redis may cost one short stall, not one per session."""
    import time

    url = "redis://10.255.255.1:6379/0"  # unroutable: a connect would wait for its timeout
    with pytest.raises(budget.BudgetUnavailable):
        budget.reserve("usd", 0.01, "first", ledger_path=url)
    start = time.monotonic()
    with pytest.raises(budget.BudgetUnavailable):
        budget.reserve("usd", 0.01, "second", ledger_path=url)
    assert time.monotonic() - start < 0.05
