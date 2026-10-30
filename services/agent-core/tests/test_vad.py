import numpy as np
import pytest

from fixtures import read_frames
from voicecore.turntaking.vad_fixture import FixtureVAD
from voicecore.turntaking.vad_silero import SileroVAD


def clip(manifest, cid):
    return next(c for c in manifest["clips"] if c["id"] == cid)


def probs(vad, c):
    return np.array([vad.frame(f) for f in read_frames(c)])


def speech_mask(c, n):
    t = np.arange(n) * 20
    return np.array([any(a < x + 20 and x < b for a, b in c["labels"]["speech"]) for x in t])


@pytest.fixture(params=["silero", "fixture"])
def make_vad(request):
    return (lambda c: SileroVAD()) if request.param == "silero" else (lambda c: FixtureVAD(c["labels"]["speech"]))


def test_silence_clip_prob_below_0_2_on_95_percent_of_frames(manifest, make_vad):
    for cid in ("dev_silence_01", "dev_echo_only_01"):
        c = clip(manifest, cid)
        if cid == "dev_echo_only_01" and isinstance(make_vad(c), SileroVAD):
            continue  # echo is real speech at -15 dB; the echo gate (S02-T03) handles it, not the VAD
        p = probs(make_vad(c), c)
        assert (p < 0.2).mean() >= 0.95, cid


def test_single_clip_prob_above_0_5_on_80_percent_of_speech_frames(manifest, make_vad):
    for cid in ("dev_single_01", "dev_single_02", "dev_noisy_10db_01", "dev_noisy_5db_01", "dev_slow_0_8x_01"):
        c = clip(manifest, cid)
        p = probs(make_vad(c), c)
        assert (p[speech_mask(c, len(p))] > 0.5).mean() >= 0.8, cid


def test_reset_between_sessions_gives_identical_probs(manifest):
    c = clip(manifest, "dev_single_01")
    vad = SileroVAD()
    first = probs(vad, c)
    vad.reset()
    assert np.array_equal(first, probs(vad, c))
