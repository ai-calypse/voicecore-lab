"""Python codec for the VoiceCore wire protocol (packages/protocol/SPEC.md)."""
import json
import struct
from dataclasses import dataclass

import numpy as np

HEADER = struct.Struct(">BBHIIQIHH")  # 28 bytes, big-endian
KIND_MIC, KIND_AGENT = 1, 2
FLAG_END_OF_STREAM = 1

REQUIRED = {
    "hello": ["version", "token", "mic", "playout"],
    "ping": ["t_client_us"],
    "text.input": ["text"],
    "mic.revoked": [],
    "client.paused": [],
    "client.resumed_playout": [],
    "playout.started": ["gen", "t_us"],
    "playout.stopped": ["gen", "reason", "t_us"],
    "cancel.ack": ["gen", "played_until_seq"],
    "welcome": ["session_id", "resume_key", "resume_window_ms", "resumed"],
    "pong": ["t_client_us", "t_server_us"],
    "user.speech_started": ["turn_id"],
    "transcript.partial": ["turn_id", "text"],
    "transcript.final": ["turn_id", "text"],
    "agent.generation_started": ["turn_id", "gen"],
    "agent.text": ["gen", "text"],
    "agent.cancel": ["gen"],
    "answer.sources": ["gen", "sources"],
    "session.ended": ["reason"],
    "client.resumed": [],
}


class FrameError(ValueError):
    pass


@dataclass(frozen=True)
class Frame:
    kind: int
    flags: int
    stream_id: int
    sequence: int
    capture_us: int
    generation_id: int
    payload: np.ndarray  # int16 samples


def decode_frame(b: bytes) -> Frame:
    if len(b) < HEADER.size:
        raise FrameError("short")
    version, kind, flags, stream_id, seq, capture_us, gen, samples, _ = HEADER.unpack_from(b)
    if version != 1:
        raise FrameError("version")
    if kind not in (KIND_MIC, KIND_AGENT):
        raise FrameError("kind")
    if len(b) - HEADER.size != 2 * samples:
        raise FrameError("length")
    return Frame(kind, flags, stream_id, seq, capture_us, gen, np.frombuffer(b, "<i2", offset=HEADER.size))


def encode_frame(f: Frame) -> bytes:
    pcm = np.asarray(f.payload, dtype="<i2")
    return HEADER.pack(1, f.kind, f.flags, f.stream_id, f.sequence, f.capture_us, f.generation_id, len(pcm), 0) + pcm.tobytes()


def decode_event(text: str) -> dict:
    try:
        e = json.loads(text)
    except json.JSONDecodeError as err:
        raise ValueError(f"event is not JSON: {err}") from None
    if not isinstance(e, dict):
        raise ValueError("event is not an object")
    req = REQUIRED.get(e.get("type")) if isinstance(e.get("type"), str) else None
    if req is None:
        raise ValueError(f"unknown event type {e.get('type')!r}")
    missing = [f for f in req if f not in e]
    if missing:
        raise ValueError(f"{e['type']}: missing {missing}")
    return e


def encode_event(e: dict) -> str:
    return json.dumps(e, separators=(",", ":"))


def event(type_: str, **fields) -> str:
    return encode_event({"type": type_, **fields})
