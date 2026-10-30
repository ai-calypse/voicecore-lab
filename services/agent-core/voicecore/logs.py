"""Log lines: an allow-list of fields (docs/ops/data-map.md), key values redacted. LOG_FORMAT=json for JSON lines."""
import json
import logging
import os
import re
import sys
import time

from voicecore import keys

ALLOWED = ("session_id", "gen", "kind", "reason", "provider", "duration_ms")
KEY_NAMES = ("DEEPGRAM_API_KEY", "OPENROUTER_API_KEY", "CARTESIA_API_KEY", "GATEWAY_SECRET")
PATTERNS = re.compile(r"sk-or-v1-\S+|sk_car_\S+|(?i:(?<=token )\S{20,})")  # key-shaped strings, loaded or not


class Formatter(logging.Formatter):
    """json_lines: one JSON object per line; else 'time LEVEL logger msg k=v'. Both keep only ALLOWED extras and redact."""

    def __init__(self, json_lines: bool = True):
        super().__init__()
        self.json_lines = json_lines
        self.values = [v for v in (keys.key(n) for n in KEY_NAMES) if v and len(v) >= 8]  # read once: keys don't change

    def redact(self, s: str) -> str:
        for v in self.values:
            s = s.replace(v, "[redacted]")
        return PATTERNS.sub("[redacted]", s)

    def format(self, r: logging.LogRecord) -> str:
        fields = {k: getattr(r, k) for k in ALLOWED if hasattr(r, k)}
        exc = self.formatException(r.exc_info) if r.exc_info else ""
        if not self.json_lines:
            line = " ".join([self.formatTime(r), r.levelname, r.name, r.getMessage(), *(f"{k}={v}" for k, v in fields.items())])
            return self.redact(line + (f"\n{exc}" if exc else ""))
        line = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(r.created)) + f".{int(r.msecs):03d}Z",
                "level": r.levelname.lower(), "logger": r.name, "msg": self.redact(r.getMessage())}
        line |= {k: self.redact(v) if isinstance(v, str) else v for k, v in fields.items()}
        if exc:
            line["exc"] = self.redact(exc)
        return json.dumps(line)


def setup():
    h = logging.StreamHandler(sys.stdout)
    h.setFormatter(Formatter(json_lines=os.environ.get("LOG_FORMAT") == "json"))
    logging.basicConfig(level=logging.INFO, handlers=[h], force=True)
    logging.getLogger("websockets").setLevel(logging.WARNING)  # one line per health probe otherwise
