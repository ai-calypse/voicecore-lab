"""Credentials: scrypt password hashes, random tokens stored only as SHA-256, and a login rate limit."""
import hashlib
import hmac
import os
import secrets
from collections import deque

SESSION_S = 7 * 86_400
LOGIN_ATTEMPTS, LOGIN_WINDOW_S = 5, 60
KEY_PREFIX = "vck_"


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    h = hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1, dklen=32)
    return f"scrypt${salt.hex()}${h.hex()}"


def check_password(password: str, stored: str | None) -> bool:
    if not stored:
        return False
    _, salt, want = stored.split("$")
    got = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=2**14, r=8, p=1, dklen=32)
    return hmac.compare_digest(got.hex(), want)


def digest(token: str) -> str:
    """Tokens and keys are stored as this, so a copy of the database grants nothing."""
    return hashlib.sha256(token.encode()).hexdigest()


def same(token: str, stored_hash: str | None) -> bool:
    return bool(stored_hash) and hmac.compare_digest(digest(token), stored_hash)


def new_token() -> str:
    return secrets.token_hex(32)


class RateLimit:
    """At most `limit` attempts per key in `window` seconds; every attempt counts, right or wrong."""

    def __init__(self, limit: int = LOGIN_ATTEMPTS, window: float = LOGIN_WINDOW_S):
        self.limit, self.window, self.seen = limit, window, {}

    def allow(self, key: str, now: float) -> bool:
        if len(self.seen) > 10_000:  # ponytail: crude reset bounds memory; one admin, one office, never near this
            self.seen = {}
        q = self.seen.setdefault(key, deque())
        while q and q[0] <= now - self.window:
            q.popleft()
        if len(q) >= self.limit:
            return False
        q.append(now)
        return True
