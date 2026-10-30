"""Breakers and the turn deadline inside a session (Step 09 Phase 6, seam 4): mock providers, fake time."""
import asyncio

import pytest
from runtime_helpers import make, mic

from voicecore.providers.mock import LLMScript, MockLLM, MockSTT, MockTTS
from voicecore.resilience import Breaker
from voicecore.runtime.session import BUSY, SPEECH_DOWN, TROUBLE, VOICE_INPUT_DOWN
from voicecore.trace import Tracer
from voicecore.turntaking.vad_fixture import FixtureVAD

pytestmark = pytest.mark.looptime


def opened(provider: str) -> Breaker:
    b = Breaker(provider)
    for _ in range(5):
        b.failure()
    return b


def texts(out) -> list[str]:
    return [e["text"] for e in out.events("agent.text")]


async def test_open_llm_breaker_answers_busy_without_calling():
    llm, events = MockLLM(LLMScript(tokens=["Hi."])), []
    s, out = await make(llm=llm, breakers={"llm": opened("llm")}, tracer=Tracer("s-test", events.append))
    await s.on_event({"type": "text.input", "text": "hi"})
    await asyncio.sleep(1)
    await s.close()
    assert texts(out) == [BUSY] and llm.calls == []
    assert ("llm", "breaker_open") in [(e["span"], e["event"]) for e in events]


async def test_open_stt_breaker_new_session_is_text_only():
    stt = MockSTT(canned="how do I install uv?")
    s, out = await make(stt=stt, vad=FixtureVAD([[200, 1200]]), breakers={"stt": opened("stt")})
    for k in range(110):
        await s.on_frame(mic(k))
        await asyncio.sleep(0.02)
    await asyncio.sleep(6)
    assert texts(out) == [VOICE_INPUT_DOWN]  # said once; the speech was ignored, not re-prompted
    assert stt.audio_ms == 0
    await s.on_event({"type": "text.input", "text": "hi"})  # typing still works
    await asyncio.sleep(1)
    await s.close()
    assert len(texts(out)) == 2 and texts(out)[1] not in (VOICE_INPUT_DOWN, BUSY, TROUBLE)


async def test_open_tts_breaker_says_speech_is_down_and_answers_in_text():
    tts = MockTTS()
    s, out = await make(tts=tts, breakers={"tts": opened("tts")})
    for q in ("hi", "and then?"):
        await s.on_event({"type": "text.input", "text": q})
        await asyncio.sleep(1)
    await s.close()
    answers = texts(out)
    assert answers.count(SPEECH_DOWN) == 1 and len(answers) == 3  # two answers in text, the notice once
    assert out.frames() == [] and tts.texts == []


async def test_turn_deadline_wraps_the_llm_only():
    trickle = MockLLM(LLMScript(tokens=[f"w{i} " for i in range(10)], first_token_ms=0, token_ms=5000))  # stall check never fires
    s, out = await make(llm=trickle)
    await s.on_event({"type": "text.input", "text": "hi"})
    await asyncio.sleep(19)
    assert texts(out) == []
    await asyncio.sleep(2)
    await s.close()
    assert len(texts(out)) == 1 and texts(out)[0].endswith(TROUBLE)


async def test_a_long_spoken_answer_is_not_cut_by_the_deadline():
    words = " ".join(f"word{i}" for i in range(60)) + "."
    s, out = await make(llm=MockLLM(LLMScript(tokens=[words], first_token_ms=0)), tts=MockTTS(ms_per_char=60))  # ~30 s of audio
    await s.on_event({"type": "text.input", "text": "hi"})
    await asyncio.sleep(45)
    await s.close()
    assert texts(out) == [words] and out.frames()[-1].flags & 1  # the end-of-stream frame went out
