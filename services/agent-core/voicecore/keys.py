"""API keys come from the dashboard's key file, the environment, or the repo's gitignored .env, in that order.
Never log them."""
import json
import os
import re
from pathlib import Path

ENV = Path(__file__).resolve().parents[3] / ".env"
VOICE = ("DEEPGRAM_API_KEY", "OPENROUTER_API_KEY")  # voice needs both: speech in and out, and the language model


def saved(path: Path | None = None) -> dict[str, str]:
    """The keys set in the dashboard (VOICECORE_KEYS_FILE): the console writes them, a new session reads them."""
    path = path or (Path(f) if (f := os.environ.get("VOICECORE_KEYS_FILE")) else None)
    try:
        return json.loads(path.read_text()) if path else {}
    except (OSError, ValueError):
        return {}


def save(path: Path, values: dict[str, str]) -> None:
    """Replace the dashboard's keys in one step, readable by this user only."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with os.fdopen(os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "w") as f:
        json.dump(values, f)
    os.replace(tmp, path)


def voice_ready() -> bool:
    return all(key(n) for n in VOICE)


def key(name: str) -> str | None:
    if v := saved().get(name):
        return v
    if os.environ.get(name):
        return os.environ[name]
    if ENV.exists():
        for line in ENV.read_text().splitlines():
            k, _, v = line.partition("=")
            if k.strip() != name:
                continue
            q = v.strip()
            if q[:1] in ("'", '"') and q[0] in q[1:]:
                v = q[1:q.index(q[0], 1)]  # quoted: everything up to the closing quote, '#' included
            else:
                v = re.sub(r"\s+#.*$", "", v).strip()  # unquoted: '#' after whitespace (even right after '=') starts a comment
            if v:
                return v  # an empty placeholder (e.g. copied from .env.example) does not hide a later line
    return None
