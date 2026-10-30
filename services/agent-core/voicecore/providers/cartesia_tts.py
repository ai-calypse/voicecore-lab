"""Cartesia streaming TTS (sonic-3.6) over WebSocket, one context per generation.

Interface checked in Context7 /websites/cartesia_ai, 2026-10-29. Cartesia's cancel only stops requests
that have not started generating, so this adapter also drops any later audio of a cancelled generation.
Within one context, audio arrives in the order the text was sent.
"""
import asyncio
import base64
import json

from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed, ConnectionClosedOK, InvalidStatus

from voicecore import keys

from .base import Audio, ProviderError, http_error

URL = "wss://api.cartesia.ai/tts/websocket?cartesia_version=2026-08-14"
MODEL = "sonic-3.6"
VOICE = "47c38ca4-5f35-497b-b1a3-415245fb35e1"  # "Daniel": clear male voice for digital assistants
MAX_CHARS = 1500  # per-session cap (budget; 1 credit per character)
_CLOSED = object()


class CartesiaTTS:
    def __init__(self, reservation, key: str | None = None, voice: str = VOICE, model: str = MODEL, url: str = URL,
                 max_chars: int = MAX_CHARS):
        self.reservation, self.voice, self.model, self.url, self.max_chars = reservation, voice, model, url, max_chars
        self._key = key or keys.key("CARTESIA_API_KEY") or ""
        self._ws = None
        self._reader = None
        self._out: asyncio.Queue = asyncio.Queue()
        self._fence = 0  # generations <= fence were cancelled
        self._lock = asyncio.Lock()
        self.chars = 0
        self.errors: list[str] = []  # per-generation failures; that generation ends without more audio

    async def _connect(self):
        try:
            self._ws = await connect(self.url, additional_headers={"X-API-Key": self._key}, open_timeout=5)
        except InvalidStatus as e:
            raise http_error(e.response.status_code, "cartesia handshake") from None
        except (OSError, TimeoutError) as e:
            raise ProviderError("retryable", f"cartesia connect: {e}") from None
        self._reader = asyncio.create_task(self._read())

    async def synth(self, gen: int, text: str, last: bool) -> None:
        if gen <= self._fence:
            return
        if self.chars + len(text) > self.max_chars:
            raise ProviderError("fatal", f"per-session TTS cap of {self.max_chars} characters reached")
        async with self._lock:
            if self._ws is None:
                await self._connect()
        self.chars += len(text)
        msg = {"model_id": self.model, "transcript": text, "voice": {"mode": "id", "id": self.voice}, "language": "en",
               "context_id": f"g{gen}", "continue": not last,
               "output_format": {"container": "raw", "encoding": "pcm_s16le", "sample_rate": 24000}}
        try:
            await self._ws.send(json.dumps(msg))
        except ConnectionClosed as e:
            raise ProviderError("retryable", f"cartesia closed: {e}") from None

    async def _read(self):
        try:
            async for raw in self._ws:
                m = json.loads(raw)
                ctx = m.get("context_id") or "g0"
                gen = int(ctx[1:]) if ctx[1:].isdigit() else 0
                if m.get("type") == "chunk":
                    self._out.put_nowait(Audio(gen, base64.b64decode(m["data"])))
                elif m.get("type") == "done":
                    self._out.put_nowait(Audio(gen, b"", last=True))
                elif m.get("type") == "error" and gen > self._fence:
                    self.errors.append(f"g{gen}: {m.get('status_code')} {m.get('message')}")
                    self._out.put_nowait(Audio(gen, b"", last=True))  # end this generation; the socket and later ones live on
        except ConnectionClosedOK:
            pass
        except ConnectionClosed as e:
            self._out.put_nowait(ProviderError("retryable", f"cartesia closed: {e}"))
        finally:
            self._out.put_nowait(_CLOSED)

    async def audio(self):
        while (a := await self._out.get()) is not _CLOSED:
            if isinstance(a, ProviderError):
                raise a
            if a.gen > self._fence:
                yield a

    async def cancel(self, gen: int) -> None:
        self._fence = max(self._fence, gen)
        if self._ws is not None:
            try:
                await self._ws.send(json.dumps({"context_id": f"g{gen}", "cancel": True}))
            except ConnectionClosed:
                pass

    async def close(self) -> None:
        if self._ws is None:
            self._out.put_nowait(_CLOSED)
            return
        await self._ws.close()
        await self._reader
