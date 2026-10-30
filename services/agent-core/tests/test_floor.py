from voicecore.turntaking.floor import Floor, Policy
from voicecore.turntaking.vad_fixture import FixtureVAD


def clip(manifest, cid):
    return next(c for c in manifest["clips"] if c["id"] == cid)


def run(policy, speech, duration_ms, finals=()):
    """Feed fixture-VAD frames through a floor; finals are (t_ms, text) transcript events. Returns events."""
    vad, floor, events = FixtureVAD(speech), Floor(policy), []
    finals = sorted(finals)
    for k in range(duration_ms // 20):
        while finals and finals[0][0] <= k * 20:
            events += floor.transcript_final(finals.pop(0)[1])
        events += floor.frame(vad.frame())
    return events


def first(events, kind):
    return next((e for e in events if e.kind == kind), None)


def test_speech_started_after_3_voiced_frames_not_2():
    assert first(run(Policy(), [[1000, 1040]], 3000), "speech_started") is None
    e = first(run(Policy(), [[1000, 1060]], 3000), "speech_started")
    assert (e.t_ms, e.onset_ms) == (1060, 1000)


def test_fixed_700_endpoints_at_labelled_end_plus_700(manifest):
    c = clip(manifest, "dev_single_01")
    end = c["labels"]["turn_end_ms"]
    e = first(run(Policy("fixed", silence_ms=700), c["labels"]["speech"], c["duration_ms"]), "endpoint")
    assert e.reason == "silence"
    assert e.t_ms == -(-end // 20) * 20 + 700  # silence starts at the first frame after the label
    assert e.silence_ms == 700


def test_mid_pause_fixed_400_cuts_inside_the_pause_adaptive_does_not(manifest):
    for cid in ("dev_mid_pause_600ms_01", "dev_mid_pause_600ms_02"):
        c = clip(manifest, cid)
        speech, end = c["labels"]["speech"], c["labels"]["turn_end_ms"]
        fixed = [e for e in run(Policy("fixed", silence_ms=400), speech, c["duration_ms"]) if e.kind == "endpoint"]
        assert fixed[0].t_ms < speech[1][0], cid
        adaptive = [e for e in run(Policy("adaptive"), speech, c["duration_ms"]) if e.kind == "endpoint"]
        assert len(adaptive) == 1 and adaptive[0].t_ms > end, cid


def test_adaptive_silence_depends_on_speech_length():
    for length, silence in ((600, 400), (2000, 700), (4000, 1000)):
        e = first(run(Policy("adaptive"), [[1000, 1000 + length]], 8000), "endpoint")
        assert e.t_ms == 1000 + length + silence, length


def test_turn_force_ends_at_15s_with_reason_max_length():
    e = first(run(Policy(), [[1000, 20000]], 21000), "endpoint")
    assert (e.t_ms, e.reason) == (16000, "max_length")


def test_asr_assisted_ends_300ms_after_punctuated_final_400ms_before_adaptive():
    speech = [[1000, 3000]]  # 2 s: adaptive waits 700 ms
    finals = [(3100, "how do I install it?")]
    asr = first(run(Policy("asr_assisted"), speech, 6000, finals), "endpoint")
    adaptive = first(run(Policy("adaptive"), speech, 6000), "endpoint")
    assert (asr.t_ms, asr.reason) == (3300, "asr")
    assert adaptive.t_ms - asr.t_ms == 400


def test_asr_assisted_without_punctuation_falls_back_to_adaptive():
    e = first(run(Policy("asr_assisted"), [[1000, 3000]], 6000, [(3100, "how do I")]), "endpoint")
    assert (e.t_ms, e.reason) == (3700, "silence")


def test_late_final_after_300ms_silence_ends_the_turn_at_once():
    e = first(run(Policy("asr_assisted"), [[1000, 3000]], 6000, [(3500, "install uv.")]), "endpoint")
    assert (e.t_ms, e.reason) == (3500, "asr")
