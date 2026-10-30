"""Provider contract suite (seam 5). Each contract runs on the mock; live variants are in test_live_providers.py."""
import asyncio

import pytest

from voicecore import budget
from voicecore.providers.base import Audio, Done, Final, Partial, ProviderError, TextDelta
from voicecore.providers.factory import make_live
from voicecore.providers.mock import LLMScript, MockLLM, MockSTT, MockTTS

SILENCE_20MS = bytes(640)


async def collect(aiter, until=lambda x: False):
    out = []
    async for x in aiter:
        out.append(x)
        if until(x):
            break
    return out


async def test_stt_events_are_partials_then_final_and_close_twice_is_fine():
    stt = MockSTT([(200, Partial("how do")), (400, Partial("how do I")), (600, Final("how do I install uv?"))])
    for _ in range(40):  # 800 ms of audio
        await stt.send(SILENCE_20MS)
    await stt.close()
    await stt.close()
    events = await collect(stt.events())
    assert [type(e) for e in events] == [Partial, Partial, Final]
    assert events[-1].text == "how do I install uv?"


@pytest.mark.looptime
async def test_llm_streams_text_then_done_and_respects_max_tokens():
    llm = MockLLM(LLMScript(tokens=["a "] * 200))
    events = await collect(llm.stream([{"role": "user", "content": "hi"}], max_tokens=80))
    assert isinstance(events[-1], Done)
    deltas = [e for e in events if isinstance(e, TextDelta)]
    assert 1 <= len(deltas) <= 80


@pytest.mark.looptime
async def test_http_429_maps_to_rate_limited():
    llm = MockLLM(LLMScript(tokens=[], error=ProviderError("rate_limited", "HTTP 429")))
    with pytest.raises(ProviderError) as e:
        await collect(llm.stream([{"role": "user", "content": "hi"}]))
    assert e.value.kind == "rate_limited"


@pytest.mark.looptime
async def test_tts_two_chunks_give_audio_tagged_with_their_generation_in_order():
    tts = MockTTS()
    await tts.synth(1, "First sentence.", last=False)
    await tts.synth(1, "Second.", last=True)
    gen1 = await collect(tts.audio(), until=lambda a: a.last)
    assert {a.gen for a in gen1} == {1}
    assert sum(len(a.pcm) for a in gen1) > 0 and gen1[-1].last
    await tts.close()


@pytest.mark.looptime
async def test_tts_after_cancel_yields_no_audio_for_that_generation():
    tts = MockTTS()
    await tts.synth(1, "A long first answer that keeps going for a while.", last=True)
    got = []

    async def read():
        async for a in tts.audio():
            got.append(a)
            if a.gen == 2 and a.last:
                return

    reader = asyncio.create_task(read())
    await asyncio.sleep(0.2)  # some gen 1 audio is out
    await tts.cancel(1)
    n = len(got)
    await tts.synth(2, "Next.", last=True)
    await asyncio.wait_for(reader, 60)
    assert all(a.gen == 2 for a in got[n:])
    await tts.close()


def test_make_live_without_a_reservation_raises():
    for kind in ("stt", "llm", "tts"):
        with pytest.raises(budget.BudgetExceeded):
            make_live(kind, None)


# Step 09 (S09-T00): a mock connection drop, shaped like the live adapter's (send and events both fail)

async def test_mock_stt_error_after_ms_raises_retryable_once():
    stt = MockSTT(canned="unused", error_after_ms=1000)
    for _ in range(50):  # exactly 1,000 ms of audio
        await stt.send(SILENCE_20MS)
    with pytest.raises(ProviderError) as e:
        await collect(stt.events())
    assert e.value.kind == "retryable"
    with pytest.raises(ProviderError) as e2:
        await stt.send(SILENCE_20MS)  # the stream is dead from now on
    assert e2.value.kind == "retryable"
