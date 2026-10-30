"""Provider contracts (S03-T01). Live and mock adapters implement the same three shapes.

Audio is PCM16 little-endian mono: 16 kHz into STT, 24 kHz out of TTS.
"""
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Protocol


class ProviderError(Exception):
    """kind: retryable (try again), rate_limited (back off), fatal (do not retry)."""

    def __init__(self, kind: str, message: str):
        assert kind in ("retryable", "rate_limited", "fatal")
        super().__init__(f"{kind}: {message}")
        self.kind = kind


@dataclass(frozen=True)
class Partial:
    text: str


@dataclass(frozen=True)
class Final:
    text: str
    speech_final: bool = False  # the provider's own endpoint; we do not rely on it


@dataclass(frozen=True)
class TextDelta:
    text: str


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    arguments: str  # JSON text as the model wrote it


@dataclass(frozen=True)
class Done:
    usage: dict = field(default_factory=dict)  # input_tokens, output_tokens, cost_usd when known


@dataclass(frozen=True)
class Audio:
    gen: int
    pcm: bytes  # 24 kHz PCM16 LE; empty on the last item of a generation
    last: bool = False


class STTStream(Protocol):
    async def send(self, pcm: bytes) -> None: ...
    def events(self) -> AsyncIterator[Partial | Final]: ...
    async def close(self) -> None: ...


class LLM(Protocol):
    def stream(self, messages: list[dict], tools: list[dict] | None = None, max_tokens: int = 80) -> AsyncIterator[TextDelta | ToolCall | Done]: ...


class TTSStream(Protocol):
    async def synth(self, gen: int, text: str, last: bool) -> None: ...
    def audio(self) -> AsyncIterator[Audio]: ...
    async def cancel(self, gen: int) -> None: ...
    async def close(self) -> None: ...


def http_error(status: int, message: str) -> ProviderError:
    """Retry class for an HTTP status: 429 backs off, other 4xx are fatal, the rest are retryable."""
    if status == 429:
        return ProviderError("rate_limited", f"HTTP 429 {message}")
    if 400 <= status < 500:
        return ProviderError("fatal", f"HTTP {status} {message}")
    return ProviderError("retryable", f"HTTP {status} {message}")
