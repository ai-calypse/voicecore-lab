"""S03-T05 (seam 9a): 20 sessions at once, seeded random provider delays, errors and stalls, fake time."""
import asyncio
import random

import pytest
from fixtures import load_manifest
from runner.inprocess import run_clip

from voicecore.providers.base import ProviderError
from voicecore.providers.mock import LLMScript, MockLLM, MockTTS
from voicecore.runtime.session import BUSY, REPROMPT
from voicecore.turntaking.vad_fixture import FixtureVAD

pytestmark = pytest.mark.looptime


def chaos_llm(rng):
    roll = rng.random()
    return MockLLM(LLMScript(tokens=["Use ", "uv ", "add. ", "Done."], first_token_ms=rng.randint(50, 2500), token_ms=rng.randint(5, 80),
                             error=ProviderError("rate_limited", "HTTP 429") if roll < 0.15 else None,
                             stall_after=1 if 0.15 <= roll < 0.25 else None))


async def test_20_sessions_with_random_delays_and_errors_all_finish_their_turn_without_leaks():
    rng = random.Random(7)
    clips = [c for c in load_manifest()["clips"] if c["split"] == "dev" and c["category"] in ("single", "noisy_10db", "slow_0_8x", "mid_pause_600ms")]
    picked = [rng.choice(clips) for _ in range(20)]
    start = asyncio.get_running_loop().time()
    results = await asyncio.gather(*[
        run_clip(c, llm=chaos_llm(rng), tts=MockTTS(first_audio_ms=rng.randint(50, 600)), vad=FixtureVAD(c["labels"]["speech"]))
        for c in picked])
    elapsed = asyncio.get_running_loop().time() - start
    for c, r in zip(picked, results):
        gens = [e["gen"] for e in r["client"] if e["type"] == "agent.generation_started"]
        assert gens, c["id"]
        last = gens[-1]
        assert any(e["type"] == "agent.text" and e["gen"] == last for e in r["client"]), c["id"]
        assert any(e["type"] == "playout.stopped" and e["gen"] == last and e["reason"] == "done" for e in r["client"]), c["id"]
        assert r["state"] == "ended"
        assert r["stt_drops"] == 0 and r["stt_queue_max"] == 50
    texts = [e["text"] for r in results for e in r["client"] if e["type"] == "agent.text"]
    assert BUSY in texts and any(REPROMPT in t for t in texts)  # the injected 429s (after 1/2/4 s backoff) and stalls really happened
    longest = max(c["duration_ms"] for c in picked) / 1000
    assert elapsed < longest + 30  # every turn finished within 30 s of fake time after the longest clip
    assert [t for t in asyncio.all_tasks() if t is not asyncio.current_task()] == []
