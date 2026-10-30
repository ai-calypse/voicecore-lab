"""Generation runtime: one Session per conversation (S03-T02..T04).

Owns turns and generations. Every outbound agent frame and answer event belongs to one generation;
a generation is alive only while it is the newest one and above the fence. Cancelling sets the fence,
stops the LLM task, tells TTS, and sends `agent.cancel` so the gateway and the browser fence too.
"""
import asyncio
import contextlib
import enum
import itertools
import logging
from collections import deque
from collections.abc import AsyncIterator, Awaitable, Callable

import numpy as np

from voicecore import protocol
from voicecore.clock import now_us
from voicecore.providers.base import LLM, Final, Partial, ProviderError, STTStream, TextDelta, TTSStream
from voicecore.resilience import Breaker
from voicecore.trace import Tracer
from voicecore.turntaking.floor import Event, Floor, Policy, power

from .text import Chunker, TranscriptAssembler, speechify

log = logging.getLogger("voicecore.session")

SYSTEM = ("You are VoiceCore, a voice assistant for a documentation site. "
          "Answer in at most two short sentences of plain spoken English.")
REPROMPT = "Sorry, could you say that again?"
TROUBLE = "Sorry, I'm having trouble answering right now. Please try again."
VOICE_LIMIT = "Voice input has reached its limit for this session. You can keep typing your questions."
VOICE_OFF = "Spoken replies have reached their limit for this session, so I'll answer in text. Close and reopen me to talk again."
BUSY = "I'm busy right now. Please try again in a moment."
VOICE_INPUT_DOWN = "Voice input is unavailable right now; you can type your question."
SPEECH_DOWN = "Spoken replies are unavailable right now, so I'll answer in text."
BUDGET_TEXT_ONLY = "Today's voice demo budget is used up. I can still point you to the right page: ask a question by typing."


class TurnDeadline(Exception):
    """The LLM part of a turn took longer than turn_deadline_s, even though tokens kept trickling in."""
BACKOFF_S = (1, 2, 4)  # after an HTTP 429 before any answer text
PAUSE_CANCEL_S = 30  # a generation paused this long on the client is cancelled
TEXT_MAX_CHARS = 500  # same limit as the gateway
MERGE_WINDOW_US = 2_500_000  # the user speaking again this soon after we ended their turn continues that turn
PREROLL_FRAMES, STT_HANGOVER_FRAMES = 15, 30  # STT hears 300 ms before speech and 600 ms after the last voiced frame
FRAME_BYTES = 960  # 20 ms at 24 kHz, PCM16

Answer = Callable[[str, list[dict]], AsyncIterator[str | dict]]  # text deltas, or events such as answer.sources


class State(enum.StrEnum):
    LISTENING = "listening"
    USER_SPEAKING = "user_speaking"
    THINKING = "thinking"
    SPEAKING = "speaking"
    ENDED = "ended"


class Session:
    def __init__(self, sid: str, *, llm: LLM, tts: TTSStream, send: Callable[[bytes | str], Awaitable[None]],
                 stt: STTStream | None = None, vad=None, policy: Policy = Policy(), tracer: Tracer | None = None,
                 answer: Answer | None = None, stall_s: float = 8.0, final_wait_s: float = 5.0,
                 tts_factory: Callable[[], TTSStream] | None = None, breakers: dict[str, Breaker] | None = None,
                 turn_deadline_s: float = 20.0, stt_factory: Callable[[], STTStream] | None = None,
                 text_only: Callable[[str], tuple[str, list[dict]]] | None = None):
        """tts_factory: builds a fresh TTS stream for the one retry after a TTS failure.
        breakers: the process's circuit breakers by provider kind (stt, llm, tts), shared by its sessions.
        stt_factory: opens a new STT stream for the one reconnect after a drop (same reservation and audio cap).
        text_only: no paid provider at all (the public budget is used up): the microphone is ignored, nothing is spoken,
        and each typed question gets text_only(question) -> (reply, sources), e.g. the closest docs section."""
        self.sid, self.llm, self.tts, self.stt, self.vad = sid, llm, tts, stt, vad
        self.tts_factory = tts_factory
        self._send = send
        self.trace = tracer or Tracer(sid)
        self.floor = Floor(policy)
        self.answer = answer or self._llm_answer
        self.stall_s, self.final_wait_s, self.turn_deadline_s = stall_s, final_wait_s, turn_deadline_s
        self.breakers = breakers or {}
        self.stt_factory, self._stt_reconnects = stt_factory, 0
        self._since_final: deque[bytes] = deque(maxlen=500)  # audio sent to STT since its last final (10 s), replayed on reconnect
        self._stt_ok = asyncio.Event()  # cleared while a dropped stream is being replaced; the sender waits on it
        self._stt_ok.set()
        self._stt_lock = asyncio.Lock()
        self._probes: set[str] = set()  # providers whose half-open probe this session holds
        self.text_only = text_only
        self._voice_input_down = text_only is not None
        self._speech_down_said = False
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
        self._preroll: deque[bytes] = deque(maxlen=PREROLL_FRAMES)
        self._frames = 0
        self._stt_open_until = -1  # frame index; only speech (plus pre-roll and hangover) is sent to STT
        self._tts_failed: dict[int, str] = {}  # generation -> error kind
        self._tts_retried: set[int] = set()
        self._tts_requested: set[int] = set()
        self._failed: set[int] = set()  # generations whose LLM answer failed (stall, error, busy): turn/result "error"
        self._voice_off = False  # told the user that speech hit its session cap
        self._answers: dict[int, str] = {}  # final answer text per generation (for a late TTS retry)
        self._stream: int | None = None  # newest mic stream id
        self._revoked_stream: int | None = None
        self._pause_timer: asyncio.Task | None = None
        self._min_lag_us: int | None = None  # min (arrival - capture end) of mic frames: client->agent clock offset
        self._last_capture_end_us: int | None = None
        self._last_voice_turn: dict | None = None  # {"gen", "text", "t_us"} of the newest turn ended by an endpoint
        self._carry = ""  # text of a turn the user turned out to be still speaking (continuation merge)
        self._finalized = False  # Finalize already sent during the current pause
        self.dropped_stale = 0
        self._tasks: list[asyncio.Task] = []

    # --- lifecycle -------------------------------------------------------------

    async def start(self):
        if self.text_only:
            if self.stt:
                with contextlib.suppress(Exception):
                    await self.stt.close()
                self.stt = None
            await self.start_generation("t0", "", reply=BUDGET_TEXT_ONLY)
        elif self.stt and not self._allow("stt"):  # voice input is down for new sessions; typing still works
            with contextlib.suppress(Exception):
                await self.stt.close()
            self.stt, self._voice_input_down = None, True
            await self.start_generation("t0", "", reply=VOICE_INPUT_DOWN)
        for p in (self.stt, self.llm, self.tts):  # open provider connections now, not on the user's first turn
            if hasattr(p, "warm"):
                self._tasks.append(asyncio.create_task(p.warm()))
        self._tasks.append(asyncio.create_task(self._tts_reader()))
        if self.stt:
            self.trace.emit("stt", "connect")
            self._tasks += [asyncio.create_task(self._stt_sender()), asyncio.create_task(self._stt_reader())]

    async def close(self):
        if self._min_lag_us is not None:  # the session-wide minimum, so short sessions get an offset too
            self.trace.emit("clock", "client_offset", client_to_agent_us=self._min_lag_us, final=True)
        self.state = State.ENDED
        self._clear_pause_timer()
        for t in [*self._tasks, *([self.task] if self.task else [])]:
            t.cancel()
        for t in [*self._tasks, *([self.task] if self.task else [])]:
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await t
        for provider in list(self._probes):  # a probe that never got an answer must not leave its breaker stuck
            self._release(provider)
        for p in (self.stt, self.tts):
            if p:
                with contextlib.suppress(Exception):
                    await p.close()

    # --- inputs ----------------------------------------------------------------

    async def on_frame(self, f: protocol.Frame):
        """One 20 ms mic frame from the gateway."""
        if self._voice_input_down:  # the user was told to type; speech would only be re-prompted
            return
        if f.stream_id == self._revoked_stream:  # the user turned this mic off; a new stream means new consent
            return
        self._stream = f.stream_id
        self._last_capture_end_us = f.capture_us + 20_000
        lag = now_us() - (f.capture_us + 20_000)
        self._min_lag_us = lag if self._min_lag_us is None else min(self._min_lag_us, lag)
        if self._frames % 250 == 0:  # every 5 s: lets the timeline put client and agent events on one clock
            self.trace.emit("clock", "client_offset", client_to_agent_us=self._min_lag_us)
        prob = self.vad.frame(f.payload) if self.vad else 0.0
        if self.stt:
            self._to_stt(f.payload.tobytes(), prob)
        for e in self.floor.frame(prob, power(f.payload), self._played_power(f.capture_us)):
            await self._on_floor(e, capture_end_us=f.capture_us + 20_000)
        if self.stt and self.floor.policy.kind == "eager" and self.floor.silence_ms() == self.floor.policy.finalize_ms:
            self._finalized = True
            await self.stt.finalize()  # ask for the final now: a punctuated one ends the turn without the full silence
        elif self.floor.silence_ms() == 0:
            self._finalized = False

    def _to_stt(self, pcm: bytes, prob: float):
        """Speech goes to STT, silence does not: STT is billed per second and capped per session.
        A 300 ms pre-roll keeps the first syllable; a 600 ms hangover lets Finalize see the whole turn."""
        k, self._frames = self._frames, self._frames + 1
        # While the agent plays, voiced frames are mostly its own echo: open STT only once the user holds the floor
        # (barge-in), and the pre-roll still carries the first syllable. Seen live: echo transcripts leaked into the next turn.
        echo = self.playing is not None or self.floor.echo_gated()  # playing now, or within the echo tail after it
        if self.floor.onset is not None or (prob >= self.floor.policy.threshold and not echo):
            self._stt_open_until = k + STT_HANGOVER_FRAMES
        if k > self._stt_open_until:
            self._preroll.append(pcm)
            return
        for chunk in [*self._preroll, pcm]:
            if self.stt_q.full():  # STT is slower than real time: drop the oldest audio, never block the floor
                self.stt_q.get_nowait()
                self.stt_drops += 1
            self.stt_q.put_nowait(chunk)
        self._preroll.clear()

    async def on_event(self, e: dict):
        t = e["type"]
        if t == "text.input":
            text = e.get("text")
            if not isinstance(text, str) or not text.strip() or len(text) > TEXT_MAX_CHARS:  # it becomes prompt and history
                self.trace.emit("turn", "text_input_rejected", kind=type(text).__name__, chars=len(text) if isinstance(text, str) else None)
                return
            self.turn_id = f"t{next(self._turns)}"
            self._carry, self._last_voice_turn = "", None
            self.trace.emit("turn", "text_input", text=e["text"])
            if self.text_only:
                reply, sources = await asyncio.to_thread(self.text_only, e["text"])  # retrieval takes CPU: keep the loop free
                await self.start_generation(self.turn_id, e["text"], reply=reply, kind="text", sources=sources)
            else:
                await self.start_generation(self.turn_id, e["text"], kind="text")
        elif t == "playout.started":
            if e["gen"] == self.gen and self.active_gen == e["gen"]:
                self.playing = (e["gen"], e["t_us"])
            self.trace.emit("playout", "started", gen=e["gen"], t_client_us=e["t_us"])
        elif t == "playout.stopped":
            if self.playing and self.playing[0] == e["gen"]:
                self.playing = None
            if e["reason"] == "done" and e["gen"] == self.active_gen:
                self.active_gen, self.state = None, State.LISTENING
                self._clear_pause_timer()
            self.trace.emit("playout", "stopped", gen=e["gen"], reason=e["reason"], t_client_us=e["t_us"])
        elif t == "cancel.ack":
            self.trace.emit("playout", "cancel_ack", gen=e["gen"], played_until_seq=e["played_until_seq"])
        elif t == "client.resumed":
            self.trace.emit("runtime", "client_resumed")
            if self.active_gen is not None:  # whatever was playing is lost; do not speak it twice
                await self.cancel(self.active_gen, "client_resumed")
        elif t == "mic.revoked":  # voice stops for this stream; text keeps working; a half-spoken turn is dropped
            self._revoked_stream = self._stream
            self.floor.reset()
            self.transcript.reset()
            self._stt_open_until, self._preroll = -1, deque(maxlen=PREROLL_FRAMES)
            if self.state == State.USER_SPEAKING:
                self.state = State.LISTENING
            self.trace.emit("client", t)
        elif t == "client.paused":
            self._clear_pause_timer()
            if self.active_gen is not None:
                self._pause_timer = asyncio.create_task(self._cancel_after_pause(self.active_gen))
            self.trace.emit("client", t)
        elif t == "client.resumed_playout":
            self._clear_pause_timer()
            self.trace.emit("client", t)
        else:
            self.trace.emit("client", t)

    async def _cancel_after_pause(self, g: int):
        await asyncio.sleep(PAUSE_CANCEL_S)
        self._pause_timer = None
        await self.cancel(g, "paused")

    def _clear_pause_timer(self):
        if self._pause_timer and self._pause_timer is not asyncio.current_task():
            self._pause_timer.cancel()
        self._pause_timer = None

    # --- turn-taking -----------------------------------------------------------

    def _played_power(self, capture_us: int) -> float | None:
        """Power of the agent audio the client was playing when this mic frame was captured (client clock).
        ponytail: assumes playback runs in real time from playout.started; a client underrun shifts its audio later
        than this model. Add periodic playout position events to the protocol if live underruns show up."""
        if not self.playing:
            return None
        g, t0 = self.playing
        off = (capture_us - t0) * 24 // 1000
        if off < 0:
            return None
        pcm = np.frombuffer(self.played.get(g, b""), "<i2")
        return power(pcm[off : off + 480])

    async def _on_floor(self, e: Event, capture_end_us: int | None = None):
        """capture_end_us: client-clock time at the end of the frame that triggered e (aligns traces with the client)."""
        if e.kind in ("speech_started", "barge_in"):
            self.turn_id = f"t{next(self._turns)}"
            self.transcript.reset()
            self.trace.emit("turn", e.kind, onset_ms=e.onset_ms, capture_end_us=capture_end_us)
            last = self._last_voice_turn
            if last and last["gen"] == self.active_gen and self.playing is None and now_us() - last["t_us"] <= MERGE_WINDOW_US:
                # We ended the turn too early (a pause inside one question): answer both parts together. Once the
                # answer is audible, new speech reacts to it (a barge-in), so it is a new question.
                self._carry = last["text"]
                self.trace.emit("turn", "continuation", gen=last["gen"], text=last["text"])
            if self.active_gen is not None:
                await self.cancel(self.active_gen, e.kind)
            self.state = State.USER_SPEAKING
            await self._event("user.speech_started", turn_id=self.turn_id)
        elif e.kind == "endpoint":
            self.trace.emit("turn", "endpoint", turn_id=self.turn_id, reason=e.reason, onset_ms=e.onset_ms, silence_ms=e.silence_ms,
                            capture_end_us=capture_end_us)
            self.state = State.THINKING
            if self.stt and not self._finalized:  # once per pause is enough
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
        text = f"{self._carry} {self.transcript.text()}".strip()
        self._carry = ""
        self.trace.emit("stt", "turn_text", turn_id=turn_id, chars=len(text), waited_ms=round(waited * 1000), text=text)
        if text:
            await self._event("transcript.final", turn_id=turn_id, text=text)
            await self.start_generation(turn_id, text, kind="voice")
            self._last_voice_turn = {"gen": self.gen, "text": text, "t_us": now_us()}
        else:
            await self.start_generation(turn_id, "", reply=REPROMPT, kind="voice")

    # --- generations -----------------------------------------------------------

    def _alive(self, g: int) -> bool:
        return g == self.gen and g > self.fence and self.state != State.ENDED

    async def start_generation(self, turn_id: str, text: str, reply: str | None = None, kind: str = "notice",
                               sources: list[dict] | None = None):
        """kind: voice (an endpointed turn), text (typed) or notice (a reply the session sends by itself)."""
        if self.active_gen is not None:
            await self.cancel(self.active_gen, "superseded")
        self.gen += 1
        g = self.gen
        self.active_gen, self.state = g, State.THINKING
        self.played = {g: bytearray()}
        self.task = asyncio.create_task(self._generate(g, turn_id, text, reply, kind, sources))

    async def cancel(self, g: int, reason: str):
        if g != self.active_gen:
            return
        self.active_gen, self.fence, self.playing = None, max(self.fence, g), None
        self.state = State.LISTENING
        self._clear_pause_timer()
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

    async def _generate(self, g: int, turn_id: str, text: str, reply: str | None, kind: str = "notice",
                        sources: list[dict] | None = None):
        await self._event("agent.generation_started", turn_id=turn_id, gen=g)
        if sources:
            await self._event("answer.sources", gen=g, sources=sources)
        chunker, said = Chunker(), []

        def sep() -> str:  # a space before an appended reply, unless the answer so far already ends with one
            return " " if said and not said[-1][-1:].isspace() else ""

        async def speak(piece: str):
            said.append(piece)
            for c in chunker.push(piece):
                await self._synth(g, c, last=False)

        if reply is not None:
            await speak(reply)
        else:
            for attempt, wait in enumerate((*BACKOFF_S, None)):
                if not self._allow("llm"):
                    self._failed.add(g)
                    await speak(BUSY)
                    break
                self.trace.emit("llm", "request", gen=g, turn_id=turn_id, attempt=attempt)
                rate_limited = await self._stream_answer(g, text, speak, sep)
                if not self._alive(g):
                    return
                if not rate_limited:
                    break
                if wait is None:
                    self._failed.add(g)
                    await speak(BUSY)
                    break
                self.trace.emit("llm", "backoff", gen=g, wait_s=wait)
                await asyncio.sleep(wait)
        await self._synth(g, chunker.flush(), last=True)
        answer = "".join(said).strip()
        if self._alive(g):
            self._answers = {g: answer}
            result = "reply" if reply is not None else "error" if g in self._failed else "answer"
            self.trace.emit("turn", "result", gen=g, turn_id=turn_id, kind=kind, result=result)
            await self._event("agent.text", gen=g, text=answer)
            if reply is None:
                self.history = [*self.history, {"role": "user", "content": text}, {"role": "assistant", "content": answer}][-8:]
            if g in self._tts_failed:
                await self._after_tts_failure(g)

    async def _after_tts_failure(self, g: int):
        """The text answer is already delivered. Retry speech once, else end the generation (no audio will end it)."""
        if g != self.active_gen:
            return
        kind = self._tts_failed.get(g)
        fatal = kind == "fatal"
        if kind not in ("breaker", "off") and not fatal and await self._retry_tts(g, self._answers.get(g, "")):
            return
        self.active_gen, self.state = None, State.LISTENING
        if kind == "breaker" and not self._speech_down_said:  # the TTS breaker is open: say so once, then text only
            self._speech_down_said = True
            await self.start_generation(self.turn_id or "t0", "", reply=SPEECH_DOWN)
        if fatal and not self._voice_off:  # e.g. the per-session TTS cap: say so once (as text), not silently
            self._voice_off = True
            await self.start_generation(self.turn_id or "t0", "", reply=VOICE_OFF)

    async def _stream_answer(self, g: int, text: str, speak, sep) -> bool:
        """Streams one answer attempt into speak(). Returns True only for an HTTP 429 before any text (retry it)."""
        it = aiter(self.answer(text, self.history))
        first = True
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self.turn_deadline_s  # the LLM only: playback after the text is done is not limited
        try:
            while True:
                left = deadline - loop.time()
                try:
                    item = await asyncio.wait_for(anext(it), max(0.0, min(self.stall_s, left)))
                except StopAsyncIteration:
                    self._verdict("llm", None)
                    return False
                except TimeoutError:
                    if loop.time() >= deadline:
                        raise TurnDeadline from None
                    raise
                if not self._alive(g):
                    self._release("llm")
                    return False
                if isinstance(item, dict):  # e.g. answer.sources from the answer engine
                    await self._event(**item, gen=g)
                    continue
                if first:
                    self.trace.emit("llm", "first_token", gen=g)
                    first = False
                await speak(item)
        except TurnDeadline:
            self.trace.emit("llm", "deadline", gen=g, after_s=self.turn_deadline_s)
            self._verdict("llm", TimeoutError())
            self._failed.add(g)
            await speak(sep() + TROUBLE)
        except TimeoutError:
            self.trace.emit("llm", "stall", gen=g, after_s=self.stall_s)
            self._verdict("llm", TimeoutError())
            self._failed.add(g)
            await speak(sep() + REPROMPT)
        except ProviderError as err:
            self._provider_error("llm", err.kind, gen=g)
            if err.kind == "rate_limited" and first:
                return True
            self._failed.add(g)
            await speak(sep() + TROUBLE)
        except Exception as err:  # never leave a turn without an answer and an end
            self.trace.emit("llm", "internal_error", gen=g, kind=type(err).__name__)  # not a provider error: our own bug
            log.exception("answer failed", extra={"session_id": self.sid, "gen": g})  # our bug, not the provider's
            self._verdict("llm", err)
            self._failed.add(g)
            await speak(sep() + TROUBLE)
        except asyncio.CancelledError:  # e.g. a barge-in: no verdict on the provider
            self._release("llm")
            raise
        finally:
            with contextlib.suppress(Exception):
                await it.aclose()
        return False

    async def _retry_tts(self, g: int, answer: str) -> bool:
        """One retry on a fresh TTS stream, only if none of this answer was heard yet (never repeat speech)."""
        if not self.tts_factory or g in self._tts_retried or self._seq.get(g) or not self._allow("tts"):
            return False
        self._tts_retried.add(g)
        self._tts_failed.pop(g, None)
        self._pcm.pop(g, None)  # never prepend a fragment of the failed attempt
        old, self.tts = self.tts, self.tts_factory()
        with contextlib.suppress(Exception):
            await old.close()
        self._tasks.append(asyncio.create_task(self._tts_reader()))
        self.trace.emit("tts", "retry", gen=g)
        c = Chunker()
        parts = [*c.push(answer + " "), c.flush()]
        for i, part in enumerate(parts):
            await self._synth(g, part, last=i == len(parts) - 1)
        return g not in self._tts_failed

    async def _synth(self, g: int, text: str, last: bool):
        if not self._alive(g):
            return
        if self.text_only:
            self._tts_failed[g] = "off"  # nothing is spoken; this ends the generation once its text is out
            return
        if self._tts_failed.get(g) in ("breaker", "off"):
            return
        spoken = speechify(text)
        if spoken or last:
            if g not in self._tts_requested:  # one per generation: the denominator of the TTS error ratio
                self._tts_requested.add(g)
                if not self._allow("tts"):
                    self._tts_failed[g] = "breaker"
                    return
                self.trace.emit("tts", "request", gen=g)
            try:
                await self.tts.synth(g, spoken, last)
            except ProviderError as err:
                if g not in self._tts_failed:  # one error per attempt, as calls are counted per attempt
                    self._provider_error("tts", err.kind, gen=g)
                self._tts_failed[g] = err.kind

    # --- audio out -------------------------------------------------------------

    async def _tts_reader(self):
        tts = self.tts  # after a retry swaps the stream, this reader ends with its old one
        while tts is self.tts:
            try:
                async for a in tts.audio():
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
                return  # the TTS stream closed
            except ProviderError as err:  # one bad item must not silence the rest of the session
                g = self.active_gen
                if g is None:  # leftovers of an answer already given up on: no attempt to charge it to
                    self.trace.emit("tts", "stale_error", kind=err.kind)
                elif g not in self._tts_failed:  # one error per attempt, as calls are counted per attempt
                    self._provider_error("tts", err.kind, gen=g)
                if g is not None:
                    self._tts_failed[g] = err.kind
                    if self.task is None or self.task.done():  # the answer text is out: handle it here (else _generate does)
                        self._tasks.append(asyncio.create_task(self._after_tts_failure(g)))

    async def _frame(self, g: int, pcm: bytes, end: bool):
        if not self._alive(g):
            self.dropped_stale += 1
            return
        seq = self._seq.get(g, 0)
        self._seq[g] = seq + 1
        if seq == 0:
            self.trace.emit("tts", "first_audio", gen=g)
            self._verdict("tts", None)
            self.state = State.SPEAKING
        self.played.setdefault(g, bytearray()).extend(pcm)
        f = protocol.Frame(protocol.KIND_AGENT, protocol.FLAG_END_OF_STREAM if end else 0, g, seq, now_us(), g,
                           np.frombuffer(pcm, "<i2"))
        await self._send(protocol.encode_frame(f))

    # --- STT -------------------------------------------------------------------

    async def _stt_sender(self):
        """Feeds queued speech to STT. Waits while a dropped stream is replaced, so replayed audio goes first."""
        while self.stt:
            chunk = await self.stt_q.get()
            await self._stt_ok.wait()
            if (stream := self.stt) is None:
                return
            self._since_final.append(chunk)
            try:
                await stream.send(chunk)
            except ProviderError as err:
                if err.kind == "fatal":  # e.g. the per-session STT cap: say so once, text still works
                    self._provider_error("stt", err.kind)
                    await self.start_generation(self.turn_id or "t0", "", reply=VOICE_LIMIT)
                    return
                await self._stt_dropped(stream, err)

    async def _stt_reader(self):
        while (stream := self.stt) is not None:
            try:
                async for e in stream.events():
                    self._verdict("stt", None)
                    if isinstance(e, Partial):
                        self.transcript.partial(e.text)
                    elif isinstance(e, Final):
                        self._since_final.clear()  # a reconnect replays only what this final has not covered
                        self.transcript.final(e.text)
                        self.trace.emit("stt", "final", text=e.text)
                        for fe in self.floor.transcript_final(e.text):  # asr_assisted: the final itself ends the turn
                            await self._on_floor(fe, capture_end_us=self._last_capture_end_us)
                    await self._event("transcript.partial", turn_id=self.turn_id or "t0", text=self.transcript.text())
                async with self._stt_lock:  # a reconnect in progress closed this stream: wait for its replacement
                    if stream is self.stt:
                        return  # closed normally, not replaced
            except ProviderError as err:
                if err.kind == "fatal":
                    self._provider_error("stt", err.kind)
                    return
                await self._stt_dropped(stream, err)

    async def _stt_dropped(self, stream: STTStream, err: ProviderError):
        """Sender and reader both report drops here; the first report for a stream handles it, so it counts once."""
        async with self._stt_lock:
            if stream is not self.stt:
                return  # already replaced (or given up on) by the other task
            self._provider_error("stt", err.kind)
            await self._stt_reconnect()

    async def _stt_reconnect(self):
        """One reconnect per session, 0.2 s after a drop. If the turn already ended, its partial becomes final now
        (no 5 s wait and nothing to replay); otherwise the new stream hears the audio since the last final again."""
        self._stt_ok.clear()  # the sender waits: nothing may reach the new stream before the replay
        try:
            ended = self.state == State.THINKING
            if ended and self.transcript.pending:
                self.transcript.final(self.transcript.pending)
            if ended:
                self._since_final.clear()
            with contextlib.suppress(Exception):
                await self.stt.close()
            if self._stt_reconnects >= 1 or not self.stt_factory or not self._allow("stt"):
                await self._voice_input_gone()
                return
            self._stt_reconnects += 1
            await asyncio.sleep(0.2)
            self.stt = self.stt_factory()
            self.trace.emit("stt", "reconnect")
            self.trace.emit("stt", "connect")
            try:
                if hasattr(self.stt, "warm"):
                    await self.stt.warm()
                for chunk in list(self._since_final):
                    await self.stt.send(chunk)
            except ProviderError as err:  # the new stream is no better: stop at its first error, not 500 retries
                self._provider_error("stt", err.kind)
                with contextlib.suppress(Exception):
                    await self.stt.close()
                await self._voice_input_gone()
        finally:
            self._stt_ok.set()

    async def _voice_input_gone(self):
        self.stt, self._voice_input_down = None, True
        await self.start_generation(self.turn_id or "t0", "", reply=VOICE_INPUT_DOWN)

    def _provider_error(self, provider: str, kind: str, gen: int | None = None):
        self.trace.emit(provider, "error", gen=gen, kind=kind)
        self._verdict(provider, ProviderError(kind, "reported"))
        extra = {"session_id": self.sid, "provider": provider, "kind": kind}
        log.warning("provider error", extra=extra if gen is None else {**extra, "gen": gen})

    def _allow(self, provider: str) -> bool:
        b = self.breakers.get(provider)
        if b is None:
            return True
        was = b.state
        if not b.allow():
            self.trace.emit(provider, "breaker_open")
            return False
        if was != "closed":
            self._probes.add(provider)
        return True

    def _verdict(self, provider: str, err: BaseException | None):
        """Any session's counted failure counts; only the probe holder's success (or no-verdict) moves the breaker."""
        b = self.breakers.get(provider)
        if b is None:
            return
        holds = provider in self._probes
        self._probes.discard(provider)
        if err is not None and Breaker.counts(err):
            b.failure()
        elif holds:
            b.record(err)

    def _release(self, provider: str):
        if provider in self._probes:
            self._probes.discard(provider)
            self.breakers[provider].release()

    async def _event(self, type: str, **fields):
        await self._send(protocol.event(type, **fields))
