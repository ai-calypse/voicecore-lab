"""API keys come from the environment or the repo's gitignored .env. Never log them."""
import os
from pathlib import Path

ENV = Path(__file__).resolve().parents[3] / ".env"


def key(name: str) -> str | None:
    if os.environ.get(name):
        return os.environ[name]
    if ENV.exists():
        for line in ENV.read_text().splitlines():
            k, _, v = line.partition("=")
            if k.strip() == name:
                return v.strip()
    return None
