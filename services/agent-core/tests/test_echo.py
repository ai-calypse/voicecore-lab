"""Echo gate on real Silero output: the fixtures mix the agent clip back in at -15 dB, 40 ms late."""
import pytest
from fixtures import played_power, read_frames

from voicecore.turntaking.floor import Floor, Policy, power
from voicecore.turntaking.vad_silero import SileroVAD


def run(manifest, cid):
    c = next(x for x in manifest["clips"] if x["id"] == cid)
    ref, playing = played_power(c, manifest["clips"])
    vad, floor, events = SileroVAD(), Floor(Policy()), []
    for k, m in enumerate(read_frames(c)):
        events += floor.frame(vad.frame(m), power(m), ref[k] if playing[k] else None)
    return c, events


@pytest.mark.parametrize("cid", ["dev_echo_only_01", "dev_echo_only_02"])
def test_echo_only_during_playout_gives_no_speech_started_or_barge_in(manifest, cid):
    assert run(manifest, cid)[1] == []


def test_interrupt_during_playout_barges_in_soon_after_the_labelled_onset(manifest):
    delays = []
    for cid in ("dev_interrupt_01", "dev_interrupt_02", "dev_interrupt_03"):
        c, events = run(manifest, cid)
        assert events[0].kind == "barge_in", cid
        delays.append(events[0].t_ms - c["labels"]["user_onset_ms"])
    assert all(0 < d <= 500 for d in delays), delays
    assert sorted(delays)[1] <= 200, delays  # median
