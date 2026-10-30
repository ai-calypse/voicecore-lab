"""Generation runtime (seam 4): mock providers, fake time (looptime)."""
import asyncio

import looptime
import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from runtime_helpers import make, mic

from voicecore import protocol
from voicecore.providers.base import Audio, Final, Partial
from voicecore.providers.mock import LLMScript, MockLLM, MockSTT, MockTTS
from voicecore.runtime.session import REPROMPT, State
from voicecore.turntaking.vad_fixture import FixtureVAD

pytestmark = pytest.mark.looptime


# S03-T02: generations and stale results

async def test_late_llm_token_for_a_cancelled_generation_never_reaches_the_outbound_queue():
    llm = MockLLM(LLMScript(tokens=["One. ", "Two. ", "Three."], first_token_ms=100, token_ms=500))
    s, out = await make(llm=llm)
    await s.on_event({"type": "text.input", "text": "first"})
    await asyncio.sleep(0.3)  # gen 1 has said "One." and is waiting for its next token
    await s.on_event({"type": "text.input", "text": "second"})
    await asyncio.sleep(5)
    kinds = out.kinds()
    cut = kinds.index("agent.cancel")
    assert "frame:1" not in kinds[cut:]
    assert [e["gen"] for e in out.events("agent.text")] == [2]
    assert out.events("agent.cancel") == [{"type": "agent.cancel", "gen": 1}]
    await s.close()


class LeakyTTS(MockTTS):
    """A provider that ignores cancel, like Cartesia for a context that already started."""

    async def audio(self):
        while (a := await self._out.get()) is not None:
            if isinstance(a, Audio):
                yield a
            else:
                return

    async def cancel(self, gen):
        pass


async def test_late_tts_audio_for_a_cancelled_generation_is_dropped():
    s, out = await make(tts=LeakyTTS(ms_per_char=200, item_delay_ms=20))
    await s.on_event({"type": "text.input", "text": "first"})
    await asyncio.sleep(0.5)
    await s.on_event({"type": "text.input", "text": "second"})
    await asyncio.sleep(30)
    kinds = out.kinds()
    assert "frame:1" in kinds[: kinds.index("agent.cancel")]
    assert "frame:1" not in kinds[kinds.index("agent.cancel") :]
    assert s.dropped_stale > 0
    await s.close()


async def test_endpoint_starts_gen_1_and_text_input_while_thinking_cancels_it_and_starts_gen_2():
    llm = MockLLM(LLMScript(tokens=["Hi."], first_token_ms=3000))
    stt = MockSTT([(1300, Final("how do I install uv?"))])
    s, out = await make(llm=llm, stt=stt, vad=FixtureVAD([[200, 1200]]))
    for k in range(110):  # 2.2 s of audio; endpoint at 1200 + 800 ms
        await s.on_frame(mic(k))
        await asyncio.sleep(0.02)
    await asyncio.sleep(0.1)
    assert out.events("agent.generation_started") == [{"type": "agent.generation_started", "turn_id": "t1", "gen": 1}]
    assert s.state == State.THINKING
    await s.on_event({"type": "text.input", "text": "never mind, how do I add a package?"})
    await asyncio.sleep(0.01)
    assert out.events("agent.cancel") == [{"type": "agent.cancel", "gen": 1}]
    assert out.events("agent.generation_started")[-1]["gen"] == 2
    assert llm.calls[0][-1]["content"] == "how do I install uv?"
    await s.close()


async def test_client_resumed_cancels_the_live_generation():
    s, out = await make()
    await s.on_event({"type": "text.input", "text": "hi"})
    await asyncio.sleep(1)
    await s.on_event({"type": "client.resumed"})
    assert out.events("agent.cancel") == [{"type": "agent.cancel", "gen": 1}]
    await s.close()


OPS = st.lists(st.one_of(
    st.tuples(st.just("text"), st.text(min_size=1, max_size=5)),
    st.tuples(st.just("sleep"), st.integers(0, 400)),
    st.tuples(st.just("started"), st.integers(0, 3)),
    st.tuples(st.just("stopped"), st.integers(0, 3)),
    st.tuples(st.just("resumed"), st.none()),
), max_size=25)


@settings(max_examples=40, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(ops=OPS)
def test_any_event_sequence_keeps_one_generation_and_never_sends_an_older_one(ops):
    async def scenario():
        s, out = await make(llm=MockLLM(LLMScript(tokens=["A. ", "B."], first_token_ms=50, token_ms=30)),
                            tts=MockTTS(first_audio_ms=20, ms_per_char=20, item_delay_ms=1))
        for op, arg in ops:
            if op == "text":
                await s.on_event({"type": "text.input", "text": arg})
            elif op == "sleep":
                await asyncio.sleep(arg / 1000)
            elif op == "started":
                await s.on_event({"type": "playout.started", "gen": s.gen - arg, "t_us": 0})
            elif op == "stopped":
                await s.on_event({"type": "playout.stopped", "gen": s.gen - arg, "reason": "done", "t_us": 0})
            else:
                await s.on_event({"type": "client.resumed"})
            assert s.active_gen in (None, s.gen)
        await asyncio.sleep(2)
        await s.close()
        for m, newest in out.msgs:  # every frame and answer event belongs to the newest generation when sent
            if isinstance(m, bytes):
                assert protocol.decode_frame(m).generation_id == newest
        cancels = [e["gen"] for e in out.events("agent.cancel")]
        assert cancels == sorted(set(cancels))

    loop = looptime.new_event_loop()  # fake time: hundreds of simulated seconds run in milliseconds
    try:
        loop.run_until_complete(scenario())
    finally:
        loop.close()


# S03-T03: incremental STT and LLM

async def test_revising_interims_then_final_give_the_llm_the_final_text_once():
    llm = MockLLM(LLMScript(tokens=["It is 16 kHz."]))
    stt = MockSTT([(500, Partial("what is")), (800, Partial("what is the")), (1300, Final("what is the sample rate"))])
    s, out = await make(llm=llm, stt=stt, vad=FixtureVAD([[200, 1200]]))
    for k in range(110):
        await s.on_frame(mic(k))
        await asyncio.sleep(0.02)
    await asyncio.sleep(1)
    assert llm.calls[0][-1]["content"] == "what is the sample rate"
    assert out.events("transcript.final") == [{"type": "transcript.final", "turn_id": "t1", "text": "what is the sample rate"}]
    await s.close()


async def test_llm_silent_for_8s_reprompts():
    llm = MockLLM(LLMScript(tokens=["Never."], stall_after=0))
    tts = MockTTS()
    s, out = await make(llm=llm, tts=tts)
    await s.on_event({"type": "text.input", "text": "hello"})
    await asyncio.sleep(7.9)
    assert out.events("agent.text") == []
    await asyncio.sleep(1)
    assert out.events("agent.text") == [{"type": "agent.text", "gen": 1, "text": REPROMPT}]
    assert out.frames()  # the reprompt is spoken
    await s.close()


async def test_mic_frames_keep_reaching_stt_while_the_llm_stalls():
    stt = MockSTT()
    s, _ = await make(llm=MockLLM(LLMScript(tokens=["x"], stall_after=0)), stt=stt)
    await s.on_event({"type": "text.input", "text": "hello"})
    for k in range(100):  # 2 s of audio while the LLM says nothing
        await s.on_frame(mic(k))
        await asyncio.sleep(0.02)
    assert stt.audio_ms == 2000 and s.stt_drops == 0
    await s.close()


# S03-T04: chunked TTS

async def test_first_agent_frame_logs_trace_span_tts_first_audio_and_frames_are_in_order():
    events = []
    from voicecore.trace import Tracer

    s, out = await make(tracer=Tracer("s-test", events.append))
    await s.on_event({"type": "text.input", "text": "hi"})
    await asyncio.sleep(3)
    assert [(e["span"], e["event"]) for e in events if e["span"] == "tts"] == [("tts", "first_audio")]
    seqs = [f.sequence for f in out.frames()]
    assert seqs == list(range(len(seqs))) and out.frames()[-1].flags == 1
    await s.close()
