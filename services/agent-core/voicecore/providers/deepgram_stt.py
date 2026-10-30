"""Deepgram live STT (nova-3) over WebSocket. Interface checked in Context7 /websites/developers_deepgram, 2026-10-29."""
import asyncio
import json
import time
from urllib.parse import urlencode

from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed, ConnectionClosedOK, InvalidStatus

from voicecore import keys

from .base import Final, Partial, ProviderError, http_error

PARAMS = {"model": "nova-3", "encoding": "linear16", "sample_rate": 16000, "channels": 1, "interim_results": "true",
          "punctuate": "true", "smart_format": "true", "endpointing": 300,
          "keyterm": ["uv", "uvx", "uv sync", "uv lock", "pyproject.toml"]}  # live run: "uv" was heard as "of", "OV" in 5/10
URL = "wss://api.deepgram.com/v1/listen?" + urlencode(PARAMS, doseq=True)
PRICE_PER_MIN = 0.0077  # nova-3 streaming, pay as you go, deepgram.com/pricing 2026-10-29
MAX_AUDIO_S = 120  # per-session cap (budget)
_CLOSED = object()


class DeepgramSTT:
    def __init__(self, reservation, key: str | None = None, url: str = URL):
        self.reservation, self.url = reservation, url
        self._key = key or keys.key("DEEPGRAM_API_KEY") or ""
        self._ws = None
        self._reader = None
        self._q: asyncio.Queue = asyncio.Queue()
        self._closed = False
        self.audio_s = 0.0
        self.request_id = None
        self._last_send = 0.0
        self._keepalive = None

    def cost_usd(self) -> float:
        return round(self.audio_s / 60 * PRICE_PER_MIN, 6)

    async def _connect(self):
        try:
            self._ws = await connect(self.url, additional_headers={"Authorization": f"Token {self._key}"}, open_timeout=5)
        except InvalidStatus as e:
            raise http_error(e.response.status_code, "deepgram listen handshake") from None
        except (OSError, TimeoutError) as e:
            raise ProviderError("retryable", f"deepgram connect: {e}") from None
        self.request_id = self._ws.response.headers.get("dg-request-id")
        self._reader = asyncio.create_task(self._read())
        self._keepalive = asyncio.create_task(self._keep_alive())

    async def _keep_alive(self):
        """Deepgram closes a socket that gets no audio for 10 s (NET-0001), e.g. after the mic is revoked."""
        while True:
            await asyncio.sleep(4)
            if time.monotonic() - self._last_send >= 4:
                try:
                    await self._ws.send(json.dumps({"type": "KeepAlive"}))
                except ConnectionClosed:
                    return

    async def finalize(self) -> None:
        if self._ws is not None and not self._closed:
            try:
                await self._ws.send(json.dumps({"type": "Finalize"}))
            except ConnectionClosed:
                pass

    async def send(self, pcm: bytes) -> None:
        if self._closed:
            return
        if self.audio_s + len(pcm) / 32000 > MAX_AUDIO_S:
            raise ProviderError("fatal", f"per-session STT cap of {MAX_AUDIO_S} s reached")
        if self._ws is None:
            await self._connect()
        self.audio_s += len(pcm) / 32000
        self._last_send = time.monotonic()
        try:
            await self._ws.send(pcm)
        except ConnectionClosed as e:
            raise ProviderError("retryable", f"deepgram closed: {e}") from None

    async def _read(self):
        pending = ""  # latest interim text with no final yet
        try:
            async for msg in self._ws:
                m = json.loads(msg)
                if m.get("type") == "Results":
                    text = m["channel"]["alternatives"][0]["transcript"]
                    if m.get("is_final"):
                        pending = ""
                        if text:
                            self._q.put_nowait(Final(text, bool(m.get("speech_final"))))
                    elif text:
                        pending = text
                        self._q.put_nowait(Partial(text))
                elif m.get("type") == "Metadata":
                    self.request_id = m.get("request_id", self.request_id)
        except ConnectionClosedOK:
            pass
        except ConnectionClosed as e:
            self._q.put_nowait(ProviderError("retryable", f"deepgram closed: {e}"))
        finally:
            if pending and self._closed:  # seen once live: the stream ended on an interim; keep the words
                self._q.put_nowait(Final(pending))
            self._q.put_nowait(_CLOSED)

    async def events(self):
        while (e := await self._q.get()) is not _CLOSED:
            if isinstance(e, ProviderError):
                raise e
            yield e

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._ws is None:
            self._q.put_nowait(_CLOSED)
            return
        self._keepalive.cancel()
        try:
            await self._ws.send(json.dumps({"type": "CloseStream"}))  # flush: remaining finals, then Metadata
            await asyncio.wait_for(asyncio.shield(self._reader), 10)
        except (ConnectionClosed, TimeoutError):
            pass
        await self._ws.close()
        await self._reader
