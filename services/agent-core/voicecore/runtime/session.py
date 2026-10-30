"""Generation runtime: one Session per conversation (S03-T02..T04).

Owns turns and generations. Every outbound agent frame and answer event belongs to one generation;
a generation is alive only while it is the newest one and above the fence. Cancelling sets the fence,
stops the LLM task, tells TTS, and sends `agent.cancel` so the gateway and the browser fence too.
"""
import asyncio
import contextlib
import enum
import itertools
from collections.abc import AsyncIterator, Awaitable, Callable

import numpy as np

from voicecore import protocol
from voicecore.clock import now_us
from voicecore.providers.base import LLM, Final, Partial, ProviderError, STTStream, TextDelta, TTSStream
from voicecore.trace import Tracer
from voicecore.turntaking.floor import Event, Floor, Policy

from .text import Chunker, TranscriptAssembler, speechify

SYSTEM = ("You are VoiceCore, a voice assistant for the uv Python package manager. "
          "Answer in at most two short sentences of plain spoken English.")
REPROMPT = "Sorry, could you say that again?"
TROUBLE = "Sorry, I'm having trouble answering right now. Please try again."
FRAME_BYTES = 960  # 20 ms at 24 kHz, PCM16

Answer = Callable[[str, list[dict]], AsyncIterator[str | dict]]  # text deltas, or events such as answer.sources


class State(enum.StrEnum):
    LISTENING = "listening"
    USER_SPEAKING = "user_speaking"
    THINKING = "thinking"
    SPEAKING = "speaking"
    ENDED = "ended"


def power(pcm: np.ndarray) -> float:
    return float(np.mean((pcm.astype(np.float64) / 32768) ** 2)) if len(pcm) else 0.0


class Session:
    def __init__(self, sid: str, *, llm: LLM, tts: TTSStream, send: Callable[[bytes | str], Awaitable[None]],
                 stt: STTStream | None = None, vad=None, policy: Policy = Policy(), tracer: Tracer | None = None,
                 answer: Answer | None = None, stall_s: float = 8.0, final_wait_s: float = 5.0):
        self.sid, self.llm, self.tts, self.stt, self.vad = sid, llm, tts, stt, vad
        self._send = send
        self.trace = tracer or Tracer(sid)
        self.floor = Floor(policy)
        self.answer = answer or self._llm_answer
        self.stall_s, self.final_wait_s = stall_s, final_wait_s
        self.state = State.LISTENING
        self.gen = 0  # newest generation id
        self.fence = 0  # generations <= fence are dead
        self.active_gen: int | None = None  # generation not yet finished playing
        self.task: asyncio.Task | None = None  # the active generation's LLM/TTS-feeding task
        self._turns = itertools.count(1)
        self.turn_id: str | None = None
        self.transcript = TranscriptAssembler()
        self.history: list[dict] = []
        self.playing: tuple[int, int] | None = None  # (gen, client t_us of its first rendered sample)
        self.played: dict[int, bytearray] = {}  # audio sent per generation (echo reference)
        self._seq: dict[int, int] = {}
        self._pcm: dict[int, bytearray] = {}
        self.stt_q: asyncio.Queue = asyncio.Queue(maxsize=50)  # 1 s of mic audio towards STT
        self.stt_drops = 0
        self.dropped_stale = 0
        self._tasks: list[asyncio.Task] = []

    # --- lifecycle -------------------------------------------------------------

    async def start(self):
        self._tasks.append(asyncio.create_task(self._tts_reader()))
        if self.stt:
            self._tasks += [asyncio.create_task(self._stt_sender()), asyncio.create_task(self._stt_reader())]

    async def close(self):
        self.state = State.ENDED
        for t in [*self._tasks, *([self.task] if self.task else [])]:
            t.cancel()
        for t in [*self._tasks, *([self.task] if self.task else [])]:
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await t
        for p in (self.stt, self.tts):
            if p:
                with contextlib.suppress(Exception):
                    await p.close()

    # --- inputs ----------------------------------------------------------------

    async def on_frame(self, f: protocol.Frame):
        """One 20 ms mic frame from the gateway."""
        if self.stt:
            if self.stt_q.full():  # STT is slower than real time: drop the oldest audio, never block the floor
                self.stt_q.get_nowait()
                self.stt_drops += 1
            self.stt_q.put_nowait(f.payload.tobytes())
        prob = self.vad.frame(f.payload) if self.vad else 0.0
        for e in self.floor.frame(prob, power(f.payload), self._played_power(f.capture_us)):
            await self._on_floor(e)

    async def on_event(self, e: dict):
        t = e["type"]
        if t == "text.input":
            self.turn_id = f"t{next(self._turns)}"
            self.trace.emit("turn", "text_input", text=e["text"])
            await self.start_generation(self.turn_id, e["text"])
        elif t == "playout.started":
            if e["gen"] == self.gen and self.active_gen == e["gen"]:
                self.playing = (e["gen"], e["t_us"])
            self.trace.emit("playout", "started", gen=e["gen"], t_client_us=e["t_us"])
        elif t == "playout.stopped":
            if self.playing and self.playing[0] == e["gen"]:
                self.playing = None
            if e["reason"] == "done" and e["gen"] == self.active_gen:
                self.active_gen, self.state = None, State.LISTENING
            self.trace.emit("playout", "stopped", gen=e["gen"], reason=e["reason"], t_client_us=e["t_us"])
        elif t == "cancel.ack":
            self.trace.emit("playout", "cancel_ack", gen=e["gen"], played_until_seq=e["played_until_seq"])
        elif t == "client.resumed":
            self.trace.emit("runtime", "client_resumed")
            if self.active_gen is not None:  # whatever was playing is lost; do not speak it twice
                await self.cancel(self.active_gen, "client_resumed")
        else:  # mic.revoked, client.paused, client.resumed_playout: recorded; recovery rules are S05-T03
            self.trace.emit("client", t)

    # --- turn-taking -----------------------------------------------------------

    def _played_power(self, capture_us: int) -> float | None:
        """Power of the agent audio the client was playing when this mic frame was captured (client clock)."""
        if not self.playing:
            return None
        g, t0 = self.playing
        off = (capture_us - t0) * 24 // 1000
        if off < 0:
            return None
        pcm = np.frombuffer(self.played.get(g, b""), "<i2")
        return power(pcm[off : off + 480])

    async def _on_floor(self, e: Event):
        if e.kind in ("speech_started", "barge_in"):
            self.turn_id = f"t{next(self._turns)}"
            self.transcript.reset()
            self.trace.emit("turn", e.kind, onset_ms=e.onset_ms)
            if self.active_gen is not None:
                await self.cancel(self.active_gen, e.kind)
            self.state = State.USER_SPEAKING
            await self._event("user.speech_started", turn_id=self.turn_id)
        elif e.kind == "endpoint":
            self.trace.emit("turn", "endpoint", reason=e.reason, onset_ms=e.onset_ms)
            self.state = State.THINKING
            if self.stt:
                await self.stt.finalize()
            self._tasks = [t for t in self._tasks if not t.done()]
            self._tasks.append(asyncio.create_task(self._after_endpoint(self.turn_id)))

    async def _after_endpoint(self, turn_id: str):
        """Wait for the STT to settle (a final and no interim left), at most final_wait_s."""
        waited = 0.0
        while (self.transcript.pending or not self.transcript.finals) and waited < self.final_wait_s:
            await asyncio.sleep(0.02)
            waited += 0.02
        if turn_id != self.turn_id:  # the user started again meanwhile
            return
        text = self.transcript.text()
        self.trace.emit("stt", "turn_text", chars=len(text), waited_ms=round(waited * 1000), text=text)
        if text:
            await self._event("transcript.final", turn_id=turn_id, text=text)
            await self.start_generation(turn_id, text)
        else:
            await self.start_generation(turn_id, "", reply=REPROMPT)

    # --- generations -----------------------------------------------------------

    def _alive(self, g: int) -> bool:
        return g == self.gen and g > self.fence and self.state != State.ENDED

    async def start_generation(self, turn_id: str, text: str, reply: str | None = None):
        if self.active_gen is not None:
            await self.cancel(self.active_gen, "superseded")
        self.gen += 1
        g = self.gen
        self.active_gen, self.state = g, State.THINKING
        self.played = {g: bytearray()}
        self.task = asyncio.create_task(self._generate(g, turn_id, text, reply))

    async def cancel(self, g: int, reason: str):
        if g != self.active_gen:
            return
        self.active_gen, self.fence, self.playing = None, max(self.fence, g), None
        self.state = State.LISTENING
        if self.task and not self.task.done() and self.task is not asyncio.current_task():
            self.task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self.task
        await self.tts.cancel(g)
        await self._event("agent.cancel", gen=g)
        self.trace.emit("runtime", "cancel", gen=g, reason=reason)

    async def _llm_answer(self, text: str, history: list[dict]):
        messages = [{"role": "system", "content": SYSTEM}, *history, {"role": "user", "content": text}]
        async for e in self.llm.stream(messages, max_tokens=80):
            if isinstance(e, TextDelta):
                yield e.text

    async def _generate(self, g: int, turn_id: str, text: str, reply: str | None):
        await self._event("agent.generation_started", turn_id=turn_id, gen=g)
        chunker, said = Chunker(), []

        async def speak(piece: str):
            said.append(piece)
            for c in chunker.push(piece):
                await self._synth(g, c, last=False)

        if reply is not None:
            await speak(reply)
        else:
            self.trace.emit("llm", "request", gen=g)
            it = aiter(self.answer(text, self.history))
            first = True
            try:
                while True:
                    try:
                        item = await asyncio.wait_for(anext(it), self.stall_s)
                    except StopAsyncIteration:
                        break
                    if not self._alive(g):
                        return
                    if isinstance(item, dict):  # e.g. answer.sources from the answer engine
                        await self._event(**item, gen=g)
                        continue
                    if first:
                        self.trace.emit("llm", "first_token", gen=g)
                        first = False
                    await speak(item)
            except TimeoutError:
                self.trace.emit("llm", "stall", gen=g, after_s=self.stall_s)
                await speak(("" if not said else " ") + REPROMPT)
            except ProviderError as err:  # recovery rules (backoff, retries) are S05-T03
                self.trace.emit("llm", "error", gen=g, kind=err.kind)
                await speak(("" if not said else " ") + TROUBLE)
            finally:
                with contextlib.suppress(Exception):
                    await it.aclose()
        await self._synth(g, chunker.flush(), last=True)
        answer = "".join(said).strip()
        if self._alive(g):
            await self._event("agent.text", gen=g, text=answer)
            if reply is None:
                self.history = [*self.history, {"role": "user", "content": text}, {"role": "assistant", "content": answer}][-8:]

    async def _synth(self, g: int, text: str, last: bool):
        if not self._alive(g):
            return
        spoken = speechify(text)
        if spoken or last:
            try:
                await self.tts.synth(g, spoken, last)
            except ProviderError as err:
                self.trace.emit("tts", "error", gen=g, kind=err.kind)

    # --- audio out -------------------------------------------------------------

    async def _tts_reader(self):
        try:
            async for a in self.tts.audio():
                if not self._alive(a.gen):
                    self.dropped_stale += 1
                    continue
                buf = self._pcm.setdefault(a.gen, bytearray())
                buf += a.pcm
                while len(buf) >= FRAME_BYTES:
                    await self._frame(a.gen, bytes(buf[:FRAME_BYTES]), end=False)
                    del buf[:FRAME_BYTES]
                if a.last:
                    await self._frame(a.gen, bytes(buf), end=True)
                    buf.clear()
        except ProviderError as err:  # TTS reconnect is S05-T03
            self.trace.emit("tts", "error", kind=err.kind)

    async def _frame(self, g: int, pcm: bytes, end: bool):
        if not self._alive(g):
            self.dropped_stale += 1
            return
        seq = self._seq.get(g, 0)
        self._seq[g] = seq + 1
        if seq == 0:
            self.trace.emit("tts", "first_audio", gen=g)
            self.state = State.SPEAKING
        self.played.setdefault(g, bytearray()).extend(pcm)
        f = protocol.Frame(protocol.KIND_AGENT, protocol.FLAG_END_OF_STREAM if end else 0, g, seq, now_us(), g,
                           np.frombuffer(pcm, "<i2"))
        await self._send(protocol.encode_frame(f))

    # --- STT -------------------------------------------------------------------

    async def _stt_sender(self):
        try:
            while True:
                await self.stt.send(await self.stt_q.get())
        except ProviderError as err:  # STT reconnect is S05-T03
            self.trace.emit("stt", "error", kind=err.kind)

    async def _stt_reader(self):
        try:
            async for e in self.stt.events():
                if isinstance(e, Partial):
                    self.transcript.partial(e.text)
                elif isinstance(e, Final):
                    self.transcript.final(e.text)
                    self.trace.emit("stt", "final", text=e.text)
                    for fe in self.floor.transcript_final(e.text):
                        await self._on_floor(fe)
                await self._event("transcript.partial", turn_id=self.turn_id or "t0", text=self.transcript.text())
        except ProviderError as err:
            self.trace.emit("stt", "error", kind=err.kind)

    async def _event(self, type: str, **fields):
        await self._send(protocol.event(type, **fields))
