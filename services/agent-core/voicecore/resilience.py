"""Circuit breakers: after repeated provider failures, stop calling for a while and fail fast (Step 09 Phase 6).

One breaker per provider kind per process, shared by every session in it and injected (never a module global),
so each test builds its own. Rules: fail_max counted failures within window_s open it for open_s, whatever
succeeded in between; then exactly one probe call is let through (half-open). The probe's success closes the
breaker; its failure, or no verdict within probe_timeout_s, opens it again. Only the probe's success can close it:
a session still streaming from before an outage must not. Only retryable and rate_limited provider errors and
timeouts count. A fatal error (a bad key, a session cap) or a bug of ours is no verdict on the provider.
"""
import time
from collections import deque
from collections.abc import Callable

from voicecore.providers.base import ProviderError

STATES = {"closed": 0, "half_open": 1, "open": 2}  # the breaker-state gauge's values


class Breaker:
    def __init__(self, provider: str, fail_max: int = 5, window_s: float = 60, open_s: float = 30, probe_timeout_s: float = 10,
                 clock: Callable[[], float] = time.monotonic, on_change: Callable[[str, str], None] | None = None):
        self.provider, self.fail_max, self.window_s, self.open_s, self.clock = provider, fail_max, window_s, open_s, clock
        self.probe_timeout_s, self._probe_at = probe_timeout_s, 0.0
        self.on_change = on_change or (lambda provider, state: None)
        self.state, self.opens = "closed", 0
        self._failures: deque[float] = deque()
        self._opened_at = 0.0

    @staticmethod
    def counts(err: BaseException) -> bool:
        return isinstance(err, TimeoutError) or (isinstance(err, ProviderError) and err.kind in ("retryable", "rate_limited"))

    def allow(self) -> bool:
        """May a call go out now? Moving from open to half-open hands out the single probe."""
        now = self.clock()
        if self.state == "closed":
            return True
        if self.state == "half_open" and now - self._probe_at >= self.probe_timeout_s:
            self._open(now)  # the probe never reported: a timeout, so a failure
        if self.state == "open" and now - self._opened_at >= self.open_s:
            self._probe_at = now
            self._set("half_open")
            return True
        return False  # open, or half-open with its probe still out

    def success(self):
        """Only the probe's success closes the breaker; in the closed state it changes nothing."""
        if self.state == "half_open":
            self._failures.clear()
            self._set("closed")

    def record(self, err: BaseException | None):
        """The verdict of one call: None is a success, a counted error a failure, anything else no verdict."""
        if err is None:
            self.success()
        elif self.counts(err):
            self.failure()
        else:
            self.release()

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

    def _open(self, now: float):
        self._failures.clear()
        self._opened_at = now
        self.opens += 1
        self._set("open")

    def _set(self, state: str):
        if state != self.state:
            self.state = state
            self.on_change(self.provider, state)
