"""Trace events in the SPEC.md section 5 shape. No transcript or answer text unless include_text."""
import json
from collections.abc import Callable
from pathlib import Path

from voicecore.clock import now_us

TEXT_FIELDS = ("text", "transcript", "answer")


class Tracer:
    def __init__(self, trace_id: str, sink: Callable[[dict], None] | None = None, process: str = "agent-core", include_text: bool = False):
        self.trace_id, self.sink, self.process, self.include_text = trace_id, sink or (lambda e: None), process, include_text

    def emit(self, span: str, event: str, gen: int | None = None, **attrs) -> dict:
        if not self.include_text:
            attrs = {k: v for k, v in attrs.items() if k not in TEXT_FIELDS}
        e = {"trace_id": self.trace_id, "span": span, "event": event, "t_mono_us": now_us(), "process": self.process, "attrs": attrs}
        if gen is not None:
            e["generation_id"] = gen
        self.sink(e)
        return e


class JsonlSink:
    """Appends one JSON line per event; close() when the session ends."""

    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self._f = path.open("a", buffering=1)

    def __call__(self, e: dict):
        self._f.write(json.dumps(e) + "\n")

    def close(self):
        self._f.close()
