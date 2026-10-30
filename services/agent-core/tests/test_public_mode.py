"""Step 09 Phase 9: when the public budget is used up, the session answers in text by pointing at the right section."""
import asyncio

import pytest
from runtime_helpers import make, mic

from voicecore.providers.mock import LLMScript, MockLLM, MockSTT, MockTTS
from voicecore.runtime.session import BUDGET_TEXT_ONLY
from voicecore.turntaking.vad_fixture import FixtureVAD

pytestmark = pytest.mark.looptime


def extract(question: str):
    return "Closest section: Endpointing.", [{"n": 1, "id": "endpointing#eager", "title": "Endpointing", "url": "http://d/e#eager"}]


async def test_cap_hit_switches_to_text_only_extractive_mode():
    llm, tts, stt = MockLLM(LLMScript(tokens=["no"])), MockTTS(), MockSTT(canned="spoken question")
    s, out = await make(llm=llm, tts=tts, stt=stt, vad=FixtureVAD([[200, 1200]]), text_only=extract)
    for k in range(110):  # speech is ignored: nothing goes to STT, nothing is re-prompted
        await s.on_frame(mic(k))
        await asyncio.sleep(0.02)
    await asyncio.sleep(6)
    await s.on_event({"type": "text.input", "text": "how does eager endpointing work?"})
    await asyncio.sleep(1)
    await s.close()
    assert [e["text"] for e in out.events("agent.text")] == [BUDGET_TEXT_ONLY, "Closest section: Endpointing."]
    assert out.events("answer.sources") == [{"type": "answer.sources", "gen": 2, "sources": extract("")[1]}]
    assert llm.calls == [] and tts.texts == [] and stt.audio_ms == 0 and out.frames() == []
