"""In-process runner adapter (seam 9a): a fixture clip through a real Session in one event loop.

Run it under looptime for fake time: a 10 s clip takes milliseconds and every run is identical.
The FakeClient stands in for the browser: it renders agent frames at 20 ms each and sends
playout events back, decoupled like a network hop.
"""
import asyncio
import json
from collections import deque

import numpy as np
from fixtures import load_manifest, read_frames, read_pcm

from voicecore import protocol
from voicecore.clock import now_us
from voicecore.providers.mock import LLMScript, MockLLM, MockSTT, MockTTS
from voicecore.runtime.session import Session, State
from voicecore.trace import Tracer
from voicecore.turntaking.floor import Policy
from voicecore.turntaking.vad_silero import SileroVAD

DEFAULT_ANSWER = "Run the standalone installer. Then check it with uv version."


class FakeClient:
    def __init__(self, net_ms: int = 0):
        """net_ms: one-way network delay applied to everything between client and session, in both directions."""
        self.net_ms = net_ms
        self.session: Session | None = None
        self.log: list[dict] = []
        self.frames = 0
        self._q: deque[protocol.Frame] = deque()
        self._fence = self._gen = 0
        self._played_seq = -1
        self._tasks: set[asyncio.Task] = set()
        self._render_task = None

    def start(self):
        self._render_task = asyncio.create_task(self._render())

    async def stop(self):
        self._render_task.cancel()
        for t in [self._render_task, *self._tasks]:
            try:
                await t
            except asyncio.CancelledError:
                pass

    async def receive(self, m):
        if self.net_ms:  # the downlink: deliver later, in order
            self._later(self._receive(m))
            return
        await self._receive(m)

    def _later(self, coro):
        async def run():
            await asyncio.sleep(self.net_ms / 1000)
            await coro

        t = asyncio.create_task(run())
        self._tasks.add(t)
        t.add_done_callback(self._tasks.discard)

    async def _receive(self, m):
        if isinstance(m, bytes):
            f = protocol.decode_frame(m)
            if f.generation_id > self._fence:
                self._q.append(f)
            return
        e = json.loads(m)
        self.log.append({"t_us": now_us(), "dir": "in", **e})
        if e["type"] == "agent.cancel":
            g = e["gen"]
            self._fence = max(self._fence, g)
            self._q = deque(f for f in self._q if f.generation_id > self._fence)
            played = -1
            if self._gen and self._gen <= self._fence:
                played = self._played_seq
                self._emit({"type": "playout.stopped", "gen": self._gen, "reason": "cancel", "t_us": now_us()})
                self._gen = 0
            self._emit({"type": "cancel.ack", "gen": g, "played_until_seq": played})

    def _emit(self, e: dict):
        self.log.append({"t_us": now_us(), "dir": "out", **e})
        if self.net_ms:
            self._later(self.session.on_event(e))
            return
        t = asyncio.create_task(self.session.on_event(e))
        self._tasks.add(t)
        t.add_done_callback(self._tasks.discard)

    async def _render(self):
        while True:
            await asyncio.sleep(0.02)
            if not self._q:
                continue
            f = self._q.popleft()
            if f.generation_id != self._gen:
                self._gen = f.generation_id
                self._emit({"type": "playout.started", "gen": self._gen, "t_us": now_us()})
            self._played_seq = f.sequence
            self.frames += 1
            if f.flags & protocol.FLAG_END_OF_STREAM:
                self._emit({"type": "playout.stopped", "gen": self._gen, "reason": "done", "t_us": now_us() + 20_000})
                self._gen = 0


def to_24k(pcm16k: np.ndarray) -> bytes:
    """Linear interpolation 16 -> 24 kHz (test audio only)."""
    t = np.arange(len(pcm16k) * 3 // 2) * (2 / 3)
    return np.interp(t, np.arange(len(pcm16k)), pcm16k).astype("<i2").tobytes()


def scripted_stt(clip):
    """Simulated STT: the clip's transcript as the final returned by Finalize at our endpoint.
    Live Deepgram behaved like this: transcript ready 0.6 ms after the endpoint (reports/latency_breakdown.md)."""
    return MockSTT(canned=clip.get("transcript")) if clip["labels"]["speech"] else MockSTT()


async def run_clip(clip, *, llm=None, tts=None, stt=None, vad=None, policy=Policy(), tail_s=20.0, trace_sink=None) -> dict:
    trace: list[dict] = []
    client = FakeClient()
    sink = (lambda e: (trace.append(e), trace_sink(e))) if trace_sink else trace.append
    s = Session(clip["id"], llm=llm or MockLLM(LLMScript(tokens=[w + " " for w in DEFAULT_ANSWER.split()])),
                tts=tts or MockTTS(), stt=stt or scripted_stt(clip), vad=vad or SileroVAD(), policy=policy,
                tracer=Tracer(clip["id"], sink), send=client.receive)
    client.session = s
    await s.start()
    client.start()
    k = 0

    async def feed(pcm):
        nonlocal k
        await s.on_frame(protocol.Frame(protocol.KIND_MIC, 0, 1, k, now_us(), 0, pcm))
        k += 1
        await asyncio.sleep(0.02)

    for pcm in read_frames(clip):
        await feed(pcm)
    silence, waited = np.zeros(320, np.int16), 0.0
    while waited < tail_s and (s.active_gen is not None or s.state != State.LISTENING):  # the mic keeps sending silence
        await feed(silence)
        waited += 0.02
    await asyncio.sleep(0.1)
    await client.stop()
    await s.close()
    return {"trace": trace, "client": client.log, "frames_played": client.frames, "state": s.state,
            "stt_drops": s.stt_drops, "stt_queue_max": s.stt_q.maxsize}


LONG_ANSWER = ("You can manage projects with uv in a few steps [1]. First create a project with uv init [1]. "
               "Then add packages with uv add [2]. Finally run your code with uv run [3].")


async def run_barge_in(clip, *, clips=None, vad=None, net_ms: int = 0) -> dict:
    """Agent answers a typed question with the clip's playout_ref audio, starting about 500 ms into the mic
    timeline (where the fixture's echo begins); the mic replays the clip (echo, plus the user for interrupt clips).
    Returns the run plus barge-in timings relative to the labelled user onset, on the one loop clock."""
    clips = clips or load_manifest()["clips"]
    ref = next(c for c in clips if c["id"] == clip["playout_ref"]["clip"])
    trace: list[dict] = []
    client = FakeClient(net_ms)
    s = Session(clip["id"], llm=MockLLM(LLMScript(tokens=[w + " " for w in LONG_ANSWER.split()], first_token_ms=0, token_ms=0)),
                tts=MockTTS(first_audio_ms=clip["playout_ref"]["offset_ms"] - 20 - 2 * net_ms, audio=to_24k(read_pcm(ref))),
                stt=MockSTT(canned=clip.get("transcript")), vad=vad or SileroVAD(), tracer=Tracer(clip["id"], trace.append),
                send=client.receive)
    client.session = s
    await s.start()
    client.start()
    t0 = now_us()
    uplink: asyncio.Queue = asyncio.Queue()

    async def deliver():  # mic frames reach the session net_ms after capture, in order
        while (item := await uplink.get()) is not None:
            f, due = item
            await asyncio.sleep(max(0.0, (due - now_us()) / 1e6))
            await s.on_frame(f)

    feeder = asyncio.create_task(deliver())
    await s.on_event({"type": "text.input", "text": "How do I manage a project with uv?"})
    for k, pcm in enumerate(read_frames(clip)):
        await asyncio.sleep(0.02)  # the frame is complete 20 ms after its first sample
        uplink.put_nowait((protocol.Frame(protocol.KIND_MIC, 0, 1, k, now_us() - 20_000, 0, pcm), now_us() + net_ms * 1000))
    uplink.put_nowait(None)
    await feeder
    await asyncio.sleep(0.5 + 2 * net_ms / 1000)
    await client.stop()
    await s.close()
    onset = clip["labels"].get("user_onset_ms")
    barge = next((e for e in trace if e["event"] == "barge_in"), None)
    started = next((e for e in client.log if e["type"] == "playout.started"), None)
    stopped = next((e for e in client.log if e["type"] == "playout.stopped"), None)
    ms = lambda t: (t - t0) / 1000  # noqa: E731
    return {"trace": trace, "client": client.log, "barge_in_ms": ms(barge["t_mono_us"]) if barge else None,
            "playout_started_ms": ms(started["t_us"]) if started else None,
            "stopped": stopped and {"reason": stopped["reason"], "t_ms": ms(stopped["t_us"])}, "onset_ms": onset,
            "interrupt_to_silence_ms": ms(stopped["t_us"]) - onset if stopped and onset is not None and stopped["reason"] == "cancel" else None,
            "interrupt_to_listening_ms": next((ms(e["t_us"]) - onset for e in client.log if e["type"] == "user.speech_started"), None)
            if onset is not None else None}
