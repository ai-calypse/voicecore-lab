import json
from pathlib import Path

import pytest

from voicecore import protocol

VECTORS = Path(__file__).resolve().parents[3] / "packages/protocol/vectors"


def load(name):
    return json.loads((VECTORS / name).read_text())


def test_golden_frames():
    vs = load("frames.json")
    for v in vs["valid"]:
        raw = bytes.fromhex(v["hex"])
        f = protocol.decode_frame(raw)
        want = dict(v["fields"], capture_us=int(v["fields"]["capture_us"]))
        got = {k: getattr(f, k) for k in want if k not in ("version", "samples", "payload")}
        assert got == {k: x for k, x in want.items() if k not in ("version", "samples", "payload")}, v["name"]
        assert list(f.payload) == v["fields"]["payload"], v["name"]
        assert protocol.encode_frame(f) == raw, v["name"]
    for v in vs["invalid"]:
        with pytest.raises(protocol.FrameError, match=v["error"]):
            protocol.decode_frame(bytes.fromhex(v["hex"]))


def test_golden_events_round_trip():
    vs = load("events.json")
    assert protocol.REQUIRED == vs["required"]
    for v in vs["valid"]:
        assert json.loads(protocol.encode_event(protocol.decode_event(json.dumps(v)))) == v
    for v in vs["invalid"]:
        with pytest.raises(ValueError):
            protocol.decode_event(v["text"])
