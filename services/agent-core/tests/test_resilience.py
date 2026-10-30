"""Circuit breaker rules (Step 09 Phase 6). Pure: the clock is injected, so these run in no time."""
import asyncio

import pytest

from voicecore.providers.base import ProviderError
from voicecore.resilience import Breaker

pytestmark = pytest.mark.looptime  # the async tests wait 10-60 s of fake time


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


def make(clock):
    return Breaker("llm", fail_max=5, window_s=60, open_s=30, clock=clock)


def test_breaker_transitions():
    c = Clock()
    b = make(c)
    for _ in range(4):
        b.failure()
    assert b.state == "closed" and b.allow()
    b.failure()  # the 5th within 60 s
    assert b.state == "open" and not b.allow()
    c.t = 29.9
    assert not b.allow()
    c.t = 30.0
    assert b.allow() and b.state == "half_open"  # exactly one probe
    assert not b.allow()
    b.success()
    assert b.state == "closed" and b.allow()
    for _ in range(5):
        b.failure()
    c.t = 60.0
    assert b.allow()  # half-open again
    b.failure()  # the probe failed: open for another 30 s
    assert b.state == "open" and not b.allow()
    c.t = 89.9
    assert not b.allow()
    c.t = 90.0
    assert b.allow()


def test_failures_spread_over_more_than_the_window_stay_closed():
    c = Clock()
    b = make(c)
    for i in range(5):
        c.t = i * 15.25  # 0 .. 61 s
        b.failure()
    assert b.state == "closed"


def test_only_retryable_rate_limited_and_timeouts_count():
    assert Breaker.counts(ProviderError("retryable", "x")) and Breaker.counts(ProviderError("rate_limited", "x"))
    assert Breaker.counts(TimeoutError())
    assert not Breaker.counts(ProviderError("fatal", "bad key")) and not Breaker.counts(KeyError("bug"))


async def test_cancelled_half_open_probe_releases_the_breaker():
    c = Clock()
    b = make(c)
    for _ in range(5):
        b.failure()
    c.t = 30.0

    async def slow():
        await asyncio.sleep(60)

    task = asyncio.create_task(b.call(slow))
    await asyncio.sleep(0)
    task.cancel()  # a barge-in cancels the probe
    with pytest.raises(asyncio.CancelledError):
        await task
    assert b.state == "open"  # not stuck half-open with no probe running
    c.t = 60.0
    assert b.allow()


async def test_probe_timeout_counts_as_failure():
    c = Clock()
    b = make(c)
    for _ in range(5):
        b.failure()
    c.t = 30.0

    async def hang():
        await asyncio.sleep(60)

    with pytest.raises(TimeoutError):
        await b.call(hang, probe_timeout_s=10)
    assert b.state == "open"


async def test_call_records_success_and_failure():
    b = make(Clock())

    async def ok():
        return 7

    async def boom():
        raise ProviderError("retryable", "503")

    assert await b.call(ok) == 7
    for _ in range(5):
        with pytest.raises(ProviderError):
            await b.call(boom)
    assert b.state == "open"


def test_a_success_never_closes_an_open_breaker_or_resets_the_count():
    c = Clock()
    b = make(c)
    for _ in range(4):
        b.failure()
    b.success()  # another session's call went through: the 5th failure within 60 s still opens it
    b.failure()
    assert b.state == "open"
    b.success()  # a session still streaming from before the outage
    assert b.state == "open" and not b.allow()


def test_a_half_open_probe_expires_after_10_s_as_a_failure():
    c = Clock()
    b = make(c)
    for _ in range(5):
        b.failure()
    c.t = 30.0
    assert b.allow()  # this session holds the probe and never reports
    c.t = 39.9
    assert not b.allow()
    c.t = 40.0
    assert not b.allow() and b.state == "open"  # the probe timed out: open for another 30 s
    c.t = 70.0
    assert b.allow()


def test_record_gives_no_verdict_for_fatal_errors_or_our_bugs():
    c = Clock()
    b = make(c)
    for _ in range(5):
        b.failure()
    c.t = 30.0
    assert b.allow()
    b.record(ProviderError("fatal", "per-session cap"))  # local, says nothing about the provider
    assert b.state == "open"  # the probe is released, not counted as a success
    b.record(None)
    assert b.state == "open"  # a success outside a probe does not close it
