"""Deepgram Aura-2 streaming TTS over one WebSocket (wss://api.deepgram.com/v1/speak).

Interface checked in Context7 /websites/developers_deepgram, 2026-10-30: send {"type":"Speak","text"}, then
{"type":"Flush"}; binary linear16 audio follows, then {"type":"Flushed"}. {"type":"Clear"} drops buffered text
and audio ({"type":"Cleared"}). At most 20 Flushes per 60 s and 2,000 characters per Speak.

Audio frames carry no generation tag. Text goes out one generation at a time, so audio belongs to the oldest
unfinished generation; the "Flushed" that answers its last Flush finishes it. A generation flushes after its
first chunk (first audio fast) and after its last one, so a usual answer costs 2 Flushes. Cancelling an
unfinished generation sends Clear (its unflushed text would otherwise be spoken with the next answer) and drops
anything that arrives before "Cleared".
"""
import asyncio
import json
from collections import deque
from urllib.parse import urlencode

from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed, InvalidStatus

from voicecore import keys

from .base import Audio, ProviderError, http_error

MODEL = "aura-2-thalia-en"
# Voices an agent may use (Deepgram's Aura-2 English list, Context7 /websites/developers_deepgram, 2026-10-31).
VOICES = {
    "aura-2-thalia-en": "Thalia: American, clear and confident",
    "aura-2-andromeda-en": "Andromeda: American, casual and expressive",
    "aura-2-helena-en": "Helena: American, caring and friendly",
    "aura-2-apollo-en": "Apollo: American, confident and casual",
    "aura-2-arcas-en": "Arcas: American, natural and smooth",
    "aura-2-aries-en": "Aries: American, warm and energetic",
    "aura-2-asteria-en": "Asteria: American, clear and knowledgeable",
    "aura-2-athena-en": "Athena: American, calm and professional",
    "aura-2-callista-en": "Callista: American, clear and professional",
    "aura-2-draco-en": "Draco: British, warm and trustworthy",
    "aura-2-electra-en": "Electra: American, professional and engaging",
}


def url_for(voice: str = MODEL) -> str:
    return "wss://api.deepgram.com/v1/speak?" + urlencode({"model": voice, "encoding": "linear16", "sample_rate": 24000})


URL = url_for(MODEL)
PRICE_PER_CHAR = 0.030 / 1000  # Aura-2 pay as you go, deepgram.com/pricing 2026-10-30
MAX_CHARS = 4000  # per-session cap (budget): about 15 spoken answers, $0.12
SPEAK_MAX = 2000  # Deepgram's limit per Speak message
_CLOSED = object()


class DeepgramTTS:
    def __init__(self, reservation, key: str | None = None, url: str = URL, max_chars: int = MAX_CHARS, ws=None):
        """ws: an already open socket (open_socket, called at session start, so the first answer skips the handshake)."""
        self.reservation, self.url, self.max_chars = reservation, url, max_chars
        self._key = key or keys.key("DEEPGRAM_API_KEY") or ""
        self._ws, self._reader = ws, None
        self._out: asyncio.Queue = asyncio.Queue()
        self._pending: deque[tuple[int, bool]] = deque()  # (gen, last) per Flush sent, oldest first
        self._order: deque[int] = deque()  # unfinished generations in the order their text was sent
        self._clearing = 0  # Clears sent and not yet confirmed: audio meanwhile belongs to cancelled text
        self._fence = 0
        self._lock = asyncio.Lock()
        self._closing = False
        self.chars = 0
        self.errors: list[str] = []
        if ws is not None:
            self._reader = asyncio.create_task(self._read())

    def cost_usd(self) -> float:
        return round(self.chars * PRICE_PER_CHAR, 6)

    async def _connect(self):
        try:
            self._ws = await connect(self.url, additional_headers={"Authorization": f"Token {self._key}"}, open_timeout=5)
        except InvalidStatus as e:
            raise http_error(e.response.status_code, "deepgram speak handshake") from None
        except (OSError, TimeoutError) as e:
            raise ProviderError("retryable", f"deepgram speak connect: {e}") from None
        self._reader = asyncio.create_task(self._read())

    async def synth(self, gen: int, text: str, last: bool) -> None:
        if gen <= self._fence:
            return
        if self.chars + len(text) > self.max_chars:
            raise ProviderError("fatal", f"per-session TTS cap of {self.max_chars} characters reached")
        async with self._lock:
            if self._ws is None:  # first use, or Deepgram closed an idle socket since the last answer
                await self._connect()
            self.chars += len(text)
            first = gen not in self._order
            if first:
                self._order.append(gen)
            msgs = [{"type": "Speak", "text": text[i:i + SPEAK_MAX]} for i in range(0, len(text), SPEAK_MAX)]
            if first or last:
                msgs.append({"type": "Flush"})
                self._pending.append((gen, last))
            try:
                for m in msgs:
                    await self._ws.send(json.dumps(m))
            except ConnectionClosed as e:
                raise ProviderError("retryable", f"deepgram speak closed: {e}") from None

    async def _read(self):
        ws = self._ws
        try:
            async for raw in ws:
                if isinstance(raw, bytes):
                    if self._order and not self._clearing:
                        self._out.put_nowait(Audio(self._order[0], raw))
                    continue
                m = json.loads(raw)
                t = m.get("type")
                if t == "Flushed" and self._pending and not self._clearing:
                    gen, last = self._pending.popleft()
                    if last and self._order and self._order[0] == gen:
                        self._order.popleft()
                        self._out.put_nowait(Audio(gen, b"", last=True))
                elif t == "Cleared":
                    self._clearing = max(0, self._clearing - 1)
                elif t in ("Warning", "Error"):
                    self.errors.append(f"{t}: {m.get('description') or m.get('message') or m}")
        except ConnectionClosed as e:
            if self._order and not self._closing:  # audio was due: the session retries TTS once
                self._out.put_nowait(ProviderError("retryable", f"deepgram speak closed: {e}"))
        finally:
            if self._ws is ws:
                self._ws = None  # idle close: the next synth reconnects
            if self._closing:
                self._out.put_nowait(_CLOSED)

    async def audio(self):
        while (a := await self._out.get()) is not _CLOSED:
            if isinstance(a, ProviderError):
                raise a
            if a.gen > self._fence:
                yield a

    async def cancel(self, gen: int) -> None:
        self._fence = max(self._fence, gen)
        unfinished = [g for g in self._order if g <= self._fence]
        self._order = deque(g for g in self._order if g > self._fence)
        self._pending = deque(p for p in self._pending if p[0] > self._fence)
        if unfinished and self._ws is not None:
            self._clearing += 1
            try:
                await self._ws.send(json.dumps({"type": "Clear"}))
            except ConnectionClosed:
                self._clearing -= 1

    async def close(self) -> None:
        self._closing = True
        if self._ws is None:
            self._out.put_nowait(_CLOSED)
            return
        await self._ws.close()
        await self._reader


async def open_socket(key: str | None = None, url: str = URL):
    """Connects ahead of use without spending anything; pass the result to DeepgramTTS(ws=...)."""
    try:
        return await connect(url, additional_headers={"Authorization": f"Token {key or keys.key('DEEPGRAM_API_KEY') or ''}"}, open_timeout=5)
    except (InvalidStatus, OSError, TimeoutError):
        return None
