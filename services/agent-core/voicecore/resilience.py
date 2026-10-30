"""Circuit breakers: after repeated provider failures, stop calling for a while and fail fast (Step 09 Phase 6).

One breaker per provider kind per process, shared by every session in it and injected (never a module global),
so each test builds its own. Rules: fail_max counted failures within window_s open it for open_s; then exactly one
probe call is let through (half-open); its success closes the breaker, its failure (or a timeout) opens it again.
Only retryable and rate_limited provider errors and timeouts count: a fatal error (a bad key, a session cap) says
nothing about the provider's health.
"""
import asyncio
import time
from collections import deque
from collections.abc import Awaitable, Callable

from voicecore.providers.base import ProviderError

STATES = {"closed": 0, "half_open": 1, "open": 2}  # the breaker-state gauge's values


class BreakerOpen(Exception):
    def __init__(self, provider: str):
        super().__init__(f"{provider} circuit breaker is open")
        self.provider = provider


class Breaker:
    def __init__(self, provider: str, fail_max: int = 5, window_s: float = 60, open_s: float = 30,
                 clock: Callable[[], float] = time.monotonic, on_change: Callable[[str, str], None] | None = None):
        self.provider, self.fail_max, self.window_s, self.open_s, self.clock = provider, fail_max, window_s, open_s, clock
        self.on_change = on_change or (lambda provider, state: None)
        self.state, self.opens = "closed", 0
        self._failures: deque[float] = deque()
        self._opened_at = 0.0

    @staticmethod
    def counts(err: BaseException) -> bool:
        return isinstance(err, TimeoutError) or (isinstance(err, ProviderError) and err.kind in ("retryable", "rate_limited"))

    def allow(self) -> bool:
        """May a call go out now? Moving from open to half-open hands out the single probe."""
        if self.state == "closed":
            return True
        if self.state == "open" and self.clock() - self._opened_at >= self.open_s:
            self._set("half_open")
            return True
        return False  # open, or half-open with its probe already out

    def success(self):
        self._failures.clear()
        self._set("closed")

    def failure(self):
        now = self.clock()
        if self.state == "half_open":
            self._open(now)
            return
        self._failures.append(now)
        while self._failures and now - self._failures[0] > self.window_s:
            self._failures.popleft()
        if len(self._failures) >= self.fail_max:
            self._open(now)

    def release(self):
        """A probe ended without an answer either way (e.g. a barge-in cancelled it): back to open, never stuck."""
        if self.state == "half_open":
            self._open(self.clock())

    async def call(self, fn: Callable[[], Awaitable], probe_timeout_s: float = 10):
        """Run one provider call through the breaker. Raises BreakerOpen without calling when it is open."""
        if not self.allow():
            raise BreakerOpen(self.provider)
        probe = self.state == "half_open"
        try:
            result = await (asyncio.wait_for(fn(), probe_timeout_s) if probe else fn())
        except asyncio.CancelledError:
            if probe:
                self.release()
            raise
        except Exception as err:
            if self.counts(err):
                self.failure()
            elif probe:
                self.success()  # the provider answered; the error was ours or the request's
            raise
        self.success()
        return result

    def _open(self, now: float):
        self._failures.clear()
        self._opened_at = now
        self.opens += 1
        self._set("open")

    def _set(self, state: str):
        if state != self.state:
            self.state = state
            self.on_change(self.provider, state)
