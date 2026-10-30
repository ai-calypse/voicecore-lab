"""S04-T03 answer schema and S04-T04 text/voice parity (seam 6), mock LLM."""
import asyncio
from pathlib import Path

import pytest

from voicecore.answer.engine import REFUSAL, AnswerEngine, Grounding
from voicecore.answer.index import Index
from voicecore.answer.ingest import ingest
from voicecore.providers.mock import LLMScript, MockLLM

DOCS = Path(__file__).resolve().parents[3] / "fixtures/docs/uv"
pytestmark = pytest.mark.timeout(900)  # a cold CI runner embeds 524 passages before the first test


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


# Conversational replies (2026-10-30): small talk and "not in the docs" are spoken, never cited facts

def test_a_reply_marked_as_conversation_is_released_without_citations_and_is_not_an_answer():
    g = Grounding(5)
    assert released(g, " ~Hi! I can help ", "with endpointing and latency.") == "Hi! I can help with endpointing and latency. "
    assert not g.answerable and g.cited == []


def test_conversation_keeps_two_sentences_and_drops_citations_and_urls():
    g = Grounding(5)
    text = released(g, "~I couldn't find that [2]. See https://x.example/a for more. Ask me about latency. Or barge-in.")
    assert text == "I couldn't find that. See for more. "


def test_engine_reply_for_small_talk_has_no_sources_and_the_prompt_lists_the_docs_topics(index):
    llm = MockLLM(LLMScript(tokens=["~Hello", "! Ask me anything about uv."]))
    engine = AnswerEngine(index, llm, name="uv", topics=["Installation", "Projects"])
    out = asyncio.run(_collect(engine.stream("hello", [])))
    assert "".join(x for x in out if isinstance(x, str)) == "Hello! Ask me anything about uv. "
    assert out[-1] == {"type": "answer.sources", "sources": []}
    assert "Installation; Projects" in llm.calls[-1][0]["content"]


async def _collect(it):
    return [x async for x in it]


def test_a_short_follow_up_is_searched_together_with_the_previous_question():
    from voicecore.answer.engine import retrieval_query

    history = [{"role": "user", "content": "What is eager endpointing?"}, {"role": "assistant", "content": "It ends turns early [1]."}]
    assert retrieval_query("And if I pause?", history) == "What is eager endpointing? And if I pause?"
    assert retrieval_query("How do I embed the widget on my own site?", history) == "How do I embed the widget on my own site?"
    assert retrieval_query("And if I pause?", []) == "And if I pause?"


def test_citations_in_cjk_or_fullwidth_brackets_count_like_square_ones():
    g = Grounding(5)  # gpt-oss-120b writes 【5】 for some answers; they were dropped as uncited
    assert released(g, "Each queue drops frames at or below the fence【5】. ", "So audio stops［2］.") == "Each queue drops frames at or below the fence[5]. So audio stops[2]. "
    assert g.cited == [5, 2]


def test_a_space_before_a_dotfile_or_flag_is_kept():
    g = Grounding(5)
    assert released(g, "Put the keys in the .env file [1].") == "Put the keys in the .env file [1]. "


def test_a_url_inside_a_code_span_is_removed_with_its_backticks():
    g = Grounding(5)
    assert released(g, "It defaults to `http://localhost:3000/`, so set it [3].") == "It defaults to, so set it [3]. "
