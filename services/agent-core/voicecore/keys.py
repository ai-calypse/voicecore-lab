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
            if k.strip() == name:
                v = re.sub(r"(^|\s+)#.*$", "", v).strip()  # a comment starts at '#' after whitespace (.env.example has them)
                if len(v) >= 2 and v[0] == v[-1] and v[0] in "'\"":
                    v = v[1:-1]
                return v or None
    return None
