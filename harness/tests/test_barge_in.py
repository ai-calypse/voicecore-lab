"""S05-T01 (seams 3 + 9a): barge-in through the whole runtime, real Silero VAD, fake time."""
import pytest
from fixtures import load_manifest
from runner.inprocess import run_barge_in

pytestmark = pytest.mark.looptime
CLIPS = load_manifest()["clips"]


def clip(cid):
    return next(c for c in CLIPS if c["id"] == cid)


@pytest.mark.parametrize("cid", ["dev_interrupt_01", "dev_interrupt_02", "dev_interrupt_03"])
async def test_interrupt_during_playout_barges_in_cancels_the_generation_and_silences_the_client(cid):
    r = await run_barge_in(clip(cid), clips=CLIPS)
    assert ("agent.cancel", 1) in [(e["type"], e.get("gen")) for e in r["client"]]
    assert r["stopped"]["reason"] == "cancel"
    assert 0 < r["interrupt_to_silence_ms"] <= 500


@pytest.mark.parametrize("cid", ["dev_echo_only_01", "dev_echo_only_02"])
async def test_echo_of_the_agent_alone_never_barges_in(cid):
    r = await run_barge_in(clip(cid), clips=CLIPS)
    assert r["barge_in_ms"] is None and r["stopped"]["reason"] == "done"
