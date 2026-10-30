"""Live provider contracts (seam 5, `-m live`). Each test reserves budget first and settles what it used."""
import asyncio
import re

import pytest
from fixtures import read_pcm

from voicecore import budget, keys
from voicecore.providers.base import Audio, Done, Final, Partial, ProviderError, TextDelta
from voicecore.providers.factory import make_live

pytestmark = pytest.mark.live


def need(name):
    if not keys.key(name):
        pytest.skip(f"{name} not set")


@pytest.fixture
def usd():
    res = budget.reserve("usd", 0.01, label="live contract test")
    spent = []
    yield res, spent
    budget.settle(res, round(sum(spent), 6))


@pytest.fixture
def credits():
    res = budget.reserve("cartesia_credits", 150, label="live contract test")
    adapters = []
    yield res, adapters
    budget.settle(res, sum(a.chars for a in adapters))


async def test_stt_partials_then_final_containing_the_key_words(manifest, usd):
    need("DEEPGRAM_API_KEY")
    res, spent = usd
    clip = next(c for c in manifest["clips"] if c["id"] == "dev_single_01")
    stt = make_live("stt", res)
    pcm = read_pcm(clip)
    for i in range(0, len(pcm), 320):
        await stt.send(pcm[i : i + 320].tobytes())
    await stt.close()
    await stt.close()
    events = [e async for e in stt.events()]
    spent.append(stt.cost_usd())
    assert events and all(isinstance(e, (Partial, Final)) for e in events)
    assert isinstance(events[-1], Final)
    heard = " ".join(e.text for e in events if isinstance(e, Final)).lower()
    words = sorted(set(re.findall(r"[a-z]{6,}", clip["transcript"])), key=len, reverse=True)[:4]
    assert sum(w in heard for w in words) >= 3, (words, heard)


async def test_stt_bad_key_is_fatal(usd):
    res, _ = usd
    stt = make_live("stt", res, key="not-a-key")
    with pytest.raises(ProviderError) as e:
        await stt.send(bytes(640))
    assert e.value.kind == "fatal"


async def test_llm_text_then_done_within_max_tokens(usd):
    need("OPENROUTER_API_KEY")
    res, spent = usd
    llm = make_live("llm", res)
    events = [e async for e in llm.stream([{"role": "user", "content": "Count from 1 to 200, separated by spaces."}], max_tokens=200)]
    spent.append(llm.cost_usd)
    assert isinstance(events[-1], Done)
    assert any(isinstance(e, TextDelta) for e in events)
    assert 0 < events[-1].usage["output_tokens"] <= 200  # gpt-oss counts its reasoning tokens here too


async def test_llm_bad_key_is_fatal(usd):
    res, _ = usd
    llm = make_live("llm", res, key="sk-or-v1-invalid")
    with pytest.raises(ProviderError) as e:
        _ = [x async for x in llm.stream([{"role": "user", "content": "hi"}])]
    assert e.value.kind == "fatal"


async def test_tts_two_chunks_give_audio_tagged_with_their_generation(credits):
    need("CARTESIA_API_KEY")
    res, adapters = credits
    tts = make_live("tts", res)
    adapters.append(tts)
    await tts.synth(1, "First sentence.", last=False)
    await tts.synth(1, " Second one.", last=True)
    got = []
    async for a in tts.audio():
        got.append(a)
        if a.last:
            break
    await tts.close()
    assert {a.gen for a in got} == {1} and got[-1].last
    assert sum(len(a.pcm) for a in got) > 24000  # more than 0.5 s of 24 kHz audio


async def test_tts_after_cancel_yields_no_audio_for_that_generation(credits):
    need("CARTESIA_API_KEY")
    res, adapters = credits
    tts = make_live("tts", res)
    adapters.append(tts)
    await tts.synth(1, "A long first answer that keeps going.", last=True)
    got = []

    async def read():
        async for a in tts.audio():
            got.append(a)
            if a.gen == 2 and a.last:
                return

    reader = asyncio.create_task(read())
    while not got:
        await asyncio.sleep(0.01)
    await tts.cancel(1)
    n = len(got)
    await tts.synth(2, "Next.", last=True)
    await asyncio.wait_for(reader, 30)
    await tts.close()
    assert all(a.gen == 2 for a in got[n:])
    assert any(a.gen == 2 and a.pcm for a in got[n:])


async def test_tts_bad_key_is_fatal(credits):
    res, _ = credits
    tts = make_live("tts", res, key="sk_car_invalid")
    with pytest.raises(ProviderError) as e:
        await tts.synth(1, "hi", last=True)
    assert e.value.kind == "fatal"
