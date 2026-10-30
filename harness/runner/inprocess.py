"""In-process runner adapter (seam 9a): a fixture clip through a real Session in one event loop.

Run it under looptime for fake time: a 10 s clip takes milliseconds and every run is identical.
The FakeClient stands in for the browser: it renders agent frames at 20 ms each and sends
playout events back, decoupled like a network hop.
"""
import asyncio
import json
from collections import deque

import numpy as np
from fixtures import read_frames

from voicecore import protocol
from voicecore.clock import now_us
from voicecore.providers.base import Final
from voicecore.providers.mock import LLMScript, MockLLM, MockSTT, MockTTS
from voicecore.runtime.session import Session, State
from voicecore.trace import Tracer
from voicecore.turntaking.floor import Policy
from voicecore.turntaking.vad_silero import SileroVAD

DEFAULT_ANSWER = "Run the standalone installer. Then check it with uv version."


class FakeClient:
    def __init__(self):
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


def scripted_stt(clip, delay_ms=300):
    """Simulated STT: the clip's transcript as one final, delay_ms after the labelled turn end (audio time)."""
    if not clip["labels"]["speech"]:
        return MockSTT()
    return MockSTT([(clip["labels"]["turn_end_ms"] + delay_ms, Final(clip["transcript"]))])


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
