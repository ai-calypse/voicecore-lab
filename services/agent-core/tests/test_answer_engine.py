"""S04-T03 answer schema and S04-T04 text/voice parity (seam 6), mock LLM."""
import asyncio
from pathlib import Path

import pytest

from voicecore.answer.engine import REFUSAL, AnswerEngine, Grounding
from voicecore.answer.index import Index
from voicecore.answer.ingest import ingest
from voicecore.providers.mock import LLMScript, MockLLM

DOCS = Path(__file__).resolve().parents[3] / "fixtures/docs/uv"


@pytest.fixture(scope="module")
def index():
    return Index(ingest(DOCS))


def released(g: Grounding, *deltas: str) -> str:
    out = []
    for d in deltas:
        out += g.push(d)
    return "".join(out + g.finish())


def test_citation_id_not_in_the_retrieved_set_is_rejected():
    g = Grounding(5)
    text = released(g, "Run uv lock [2][9]. ", "It writes uv.lock [7].")
    assert text == "Run uv lock [2]. "
    assert g.cited == [2]


def test_urls_written_by_the_model_never_pass():
    g = Grounding(5)
    assert released(g, "See https://evil.example/x for the installer [1].") == "See for the installer [1]. "


def test_an_answer_without_any_valid_citation_becomes_the_refusal():
    g = Grounding(5)
    assert released(g, "uv costs 99 dollars a month.") == REFUSAL
    assert not g.answerable


def test_unanswerable_reply_is_the_fixed_refusal_with_no_sources():
    g = Grounding(5)
    assert released(g, "I couldn't find that in the docs.") == REFUSAL
    assert g.cited == [] and not g.answerable


async def test_engine_streams_grounded_text_then_sources_from_passages(index):
    llm = MockLLM(LLMScript(tokens=["Run ", "the ", "installer ", "[1]. ", "Then ", "restart ", "[2]."], first_token_ms=1, token_ms=1))
    engine = AnswerEngine(index, llm)
    items = [x async for x in engine.stream("How do I install uv on macOS?", [])]
    text = "".join(i for i in items if isinstance(i, str))
    sources = items[-1]
    assert text == "Run the installer [1]. Then restart [2]. "
    assert sources["type"] == "answer.sources" and [s["n"] for s in sources["sources"]] == [1, 2]
    assert all(s["url"].startswith("https://docs.astral.sh/uv/") for s in sources["sources"])
    prompt = llm.calls[0][-1]["content"]
    assert "[1]" in prompt and "Question: How do I install uv on macOS?" in prompt
    assert engine.last.answerable and engine.last.text == text.strip()


async def test_same_question_as_text_and_as_voice_gives_the_same_citations_and_no_brackets_in_speech(index):
    from runtime_helpers import make, mic

    from voicecore.providers.mock import MockSTT, MockTTS
    from voicecore.turntaking.vad_fixture import FixtureVAD

    question = "How do I install uv?"
    script = LLMScript(tokens=["Use ", "the ", "standalone ", "installer ", "[1]."], first_token_ms=1, token_ms=1)
    results = {}
    for mode in ("text", "voice"):
        tts = MockTTS(first_audio_ms=1)
        engine = AnswerEngine(index, MockLLM(script))
        if mode == "text":
            s, out = await make(answer=engine.stream, tts=tts)
            await s.on_event({"type": "text.input", "text": question})
        else:
            s, out = await make(answer=engine.stream, tts=tts, stt=MockSTT(canned=question), vad=FixtureVAD([[0, 1000]]))
            for k in range(100):
                await s.on_frame(mic(k))
                await asyncio.sleep(0.02)
        await asyncio.sleep(2)
        results[mode] = ([x["id"] for x in out.events("answer.sources")[0]["sources"]], tts.texts, out.events("agent.text")[0]["text"])
        await s.close()
    assert results["text"][0] == results["voice"][0] and results["text"][2] == results["voice"][2]
    assert all("[" not in t for t in results["voice"][1]) and results["voice"][1]


def test_a_refusal_after_a_grounded_sentence_is_dropped_not_counted():
    g = Grounding(5)
    assert released(g, "Run uv init [1]. ", "I couldn't find that in the docs.") == "Run uv init [1]. "
    assert g.answerable
