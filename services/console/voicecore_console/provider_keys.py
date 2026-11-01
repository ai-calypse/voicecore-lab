"""Provider keys entered in the dashboard: each is checked with one free, read-only call to its provider before it is
saved, so a typo shows up here rather than as a silent conversation."""
import httpx

NAMES = {"deepgram": "DEEPGRAM_API_KEY", "openrouter": "OPENROUTER_API_KEY"}
LABELS = {"deepgram": "Deepgram", "openrouter": "OpenRouter"}
CHECKS = {  # endpoints that describe the key itself: no spend
    "deepgram": ("https://api.deepgram.com/v1/auth/token", "Token"),
    "openrouter": ("https://openrouter.ai/api/v1/key", "Bearer"),
}


class Unreachable(Exception):
    pass


def check(provider: str, key: str) -> bool:
    """True: the provider accepts the key. False: it refuses it. Unreachable: no answer to go on."""
    url, scheme = CHECKS[provider]
    try:
        r = httpx.get(url, headers={"Authorization": f"{scheme} {key}"}, timeout=10)
    except httpx.HTTPError:
        raise Unreachable(provider) from None
    if r.status_code in (401, 403):
        return False
    if r.status_code != 200:
        raise Unreachable(provider)
    return True
