"""API keys come from the environment or the repo's gitignored .env. Never log them."""
import os
import re
from pathlib import Path

ENV = Path(__file__).resolve().parents[3] / ".env"


def key(name: str) -> str | None:
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
