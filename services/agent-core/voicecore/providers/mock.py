"""Scripted mock providers. They are also the fault injector: delays, errors and stalls come from the script."""
import asyncio
import math
from collections.abc import Callable
from dataclasses import dataclass, field

import numpy as np

from .base import Audio, Done, Final, Partial, ProviderError, TextDelta, ToolCall

_CLOSED = object()


class MockSTT:
    """Emits each scripted event once `t_ms` of audio has been received (audio time, not wall time)."""

    def __init__(self, script: list[tuple[int, Partial | Final]] = (), error: ProviderError | None = None,
                 canned: str | list[str] | None = None, error_after_ms: int | None = None):
        """canned: text returned as a Final on every finalize() (for runs where nobody scripted the words);
        a list gives one text per finalize, in order.
        error_after_ms: the connection drops once this much audio was sent, like the live adapter: events() raises
        a retryable ProviderError, and so does every later send()."""
        self.script = sorted(script, key=lambda x: x[0])
        self.error, self.canned, self.error_after_ms = error, canned, error_after_ms
        self._dropped = False
        self.finalizes = 0
        self.audio_ms = 0
        self._q: asyncio.Queue = asyncio.Queue()
        self._closed = False

    async def send(self, pcm: bytes) -> None:
        if self._dropped:
            raise ProviderError("retryable", "mock stt: connection dropped")
        if self._closed:
            return
        self.audio_ms += len(pcm) // 32
        if self.error_after_ms is not None and self.audio_ms >= self.error_after_ms:
            self._dropped = True
            self._q.put_nowait(ProviderError("retryable", "mock stt: connection dropped"))
            return
        while self.script and self.script[0][0] <= self.audio_ms:
            self._q.put_nowait(self.script.pop(0)[1])

    async def finalize(self) -> None:
        self.finalizes += 1
        text = self.canned.pop(0) if isinstance(self.canned, list) and self.canned else self.canned
        if isinstance(text, str) and not self._closed:
            self._q.put_nowait(Final(text, speech_final=True))

    async def events(self):
        if self.error:
            raise self.error
        while (e := await self._q.get()) is not _CLOSED:
            if isinstance(e, ProviderError):
                raise e
            yield e

    async def close(self) -> None:
        if not self._closed:
            self._closed = True
            self._q.put_nowait(_CLOSED)


@dataclass
class LLMScript:
    tokens: list[str]
    first_token_ms: int = 200
    token_ms: int = 15
    error: ProviderError | None = None
    stall_after: int | None = None  # stop sending (but stay open) after this many tokens
    tool_calls: list[ToolCall] = field(default_factory=list)


class MockLLM:
    """script: one LLMScript, or a function from the messages to one (for multi-turn tests)."""

    def __init__(self, script: LLMScript | Callable[[list[dict]], LLMScript]):
        self.script = script
        self.calls: list[list[dict]] = []

    async def stream(self, messages, tools=None, max_tokens=80):
        self.calls.append(messages)
        s = self.script(messages) if callable(self.script) else self.script
        await asyncio.sleep(s.first_token_ms / 1000)
        if s.error:
            raise s.error
        for call in s.tool_calls:
            yield call
        for i, tok in enumerate(s.tokens[:max_tokens]):
            if s.stall_after is not None and i >= s.stall_after:
                await asyncio.sleep(3600)
            yield TextDelta(tok)
            await asyncio.sleep(s.token_ms / 1000)
        yield Done({"input_tokens": 0, "output_tokens": min(len(s.tokens), max_tokens), "cost_usd": 0.0})


class MockTTS:
    """Synthesises a 220 Hz tone, `ms_per_char` per character, in 20 ms items, faster than real time.

    Jobs run in order on one worker, so audio within a generation follows the text order.
    """

    def __init__(self, first_audio_ms: int = 150, ms_per_char: int = 60, item_delay_ms: int = 2, error: ProviderError | None = None,
                 audio: bytes | None = None):
        """audio: 24 kHz PCM16 to speak for each generation instead of a tone (barge-in scenarios replay a known clip)."""
        self.first_audio_ms, self.ms_per_char, self.item_delay_ms, self.error = first_audio_ms, ms_per_char, item_delay_ms, error
        self.audio_clip = audio
        self._jobs: asyncio.Queue = asyncio.Queue()
        self._out: asyncio.Queue = asyncio.Queue()
        self._fence = 0
        self._started: set[int] = set()
        self._worker = None
        self.chars = 0
        self.texts: list[str] = []  # what was sent to be spoken (tests check it)

    async def synth(self, gen: int, text: str, last: bool) -> None:
        if self._worker is None:
            self._worker = asyncio.create_task(self._run())
        self.chars += len(text)
        if text:
            self.texts.append(text)
        self._jobs.put_nowait((gen, text, last))

    async def _run(self):
        while (job := await self._jobs.get()) is not _CLOSED:
            gen, text, last = job
            if gen <= self._fence:
                continue
            if self.error:
                self._out.put_nowait(self.error)
                continue
            first = gen not in self._started
            if first:
                self._started.add(gen)
                await asyncio.sleep(self.first_audio_ms / 1000)
            if self.audio_clip is not None:
                items = [self.audio_clip[i : i + 960] for i in range(0, len(self.audio_clip), 960)] if first else []
            else:
                tone = (np.sin(2 * np.pi * 220 * np.arange(480) / 24000) * 6000).astype("<i2").tobytes()
                items = [tone] * max(1, math.ceil(len(text) * self.ms_per_char / 20))
            for pcm in items:
                if gen <= self._fence:
                    break
                self._out.put_nowait(Audio(gen, pcm))
                await asyncio.sleep(self.item_delay_ms / 1000)
            if last and gen > self._fence:
                self._out.put_nowait(Audio(gen, b"", last=True))
        self._out.put_nowait(_CLOSED)

    async def audio(self):
        while (a := await self._out.get()) is not _CLOSED:
            if isinstance(a, ProviderError):
                raise a
            if a.gen > self._fence:  # adapter-side drop: nothing of a cancelled generation leaves
                yield a

    async def cancel(self, gen: int) -> None:
        self._fence = max(self._fence, gen)

    async def close(self) -> None:
        self._jobs.put_nowait(_CLOSED)
        if self._worker is None:
            self._out.put_nowait(_CLOSED)
        else:
            await self._worker
