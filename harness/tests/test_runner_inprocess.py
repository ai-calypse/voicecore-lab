import pytest
from fixtures import load_manifest
from runner.inprocess import run_clip

pytestmark = pytest.mark.looptime


async def test_inprocess_run_of_a_single_clip_gives_endpoint_generation_1_and_audio_out():
    clip = next(c for c in load_manifest()["clips"] if c["id"] == "dev_single_01")
    r = await run_clip(clip)
    spans = [(e["span"], e["event"]) for e in r["trace"]]
    for want in [("turn", "speech_started"), ("turn", "endpoint"), ("llm", "request"), ("llm", "first_token"),
                 ("tts", "first_audio"), ("playout", "started"), ("playout", "stopped")]:
        assert want in spans, want
    client = [(e["type"], e.get("gen")) for e in r["client"]]
    assert ("agent.generation_started", 1) in client
    assert ("playout.started", 1) in client and ("playout.stopped", 1) in client
    assert r["frames_played"] > 50
    endpoint = next(e for e in r["trace"] if e["event"] == "endpoint")
    assert endpoint["t_mono_us"] >= clip["labels"]["turn_end_ms"] * 1000  # never before the user finished


async def test_silence_clip_starts_no_generation():
    clip = next(c for c in load_manifest()["clips"] if c["id"] == "dev_silence_01")
    r = await run_clip(clip)
    assert not [e for e in r["client"] if e["type"] == "agent.generation_started"]
