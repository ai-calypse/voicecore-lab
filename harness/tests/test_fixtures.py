import array
import hashlib
import json
import wave

import pytest

import fixtures

ROOT = fixtures.ROOT


def test_manifest_files_exist_with_matching_sha256():
    clips = fixtures.load_manifest()["clips"]
    assert clips
    for c in clips:
        data = (ROOT / "fixtures/audio" / c["file"]).read_bytes()
        assert hashlib.sha256(data).hexdigest() == c["sha256"], c["id"]


def clip(id_):
    return next(c for c in fixtures.load_manifest()["clips"] if c["id"] == id_)


def test_every_clip_is_mono_pcm16_16khz():
    for c in fixtures.load_manifest()["clips"]:
        with wave.open(str(ROOT / "fixtures/audio" / c["file"])) as w:
            assert (w.getnchannels(), w.getsampwidth(), w.getframerate()) == (1, 2, 16000), c["id"]


def test_dev_and_holdout_share_no_speaker_and_agent_speakers_are_never_users():
    m = fixtures.load_manifest()
    speakers = {s: {c["source"]["speaker"] for c in m["clips"] if c["split"] == s and "speaker" in c["source"]}
                for s in ("dev", "holdout")}
    assert speakers["dev"] and speakers["holdout"]
    assert not speakers["dev"] & speakers["holdout"]
    assert not set(m["agent_speakers"].values()) & (speakers["dev"] | speakers["holdout"])


def split_audio(m, split):
    """Every clip hash and source utterance a split uses, including the agent track it echoes."""
    by_id = {c["id"]: c for c in m["clips"]}
    used = [c for c in m["clips"] if c["split"] == split]
    used += [by_id[c["playout_ref"]["clip"]] for c in used if "playout_ref" in c]
    return {c["sha256"] for c in used}, {u for c in used for u in c["source"].get("utterances", [])}


def test_no_audio_or_source_utterance_is_shared_between_dev_and_holdout():
    m = fixtures.load_manifest()
    (dev_sha, dev_utts), (hold_sha, hold_utts) = split_audio(m, "dev"), split_audio(m, "holdout")
    assert not dev_sha & hold_sha
    assert not dev_utts & hold_utts


def voiced_bounds_ms(path):
    """First/last 20 ms window with peak >= 500, read straight from the file."""
    with wave.open(str(path)) as w:
        x = array.array("h", w.readframes(w.getnframes()))
    peaks = [max(abs(v) for v in x[i:i + 320]) for i in range(0, len(x) - 319, 320)]
    voiced = [i for i, p in enumerate(peaks) if p >= 500]
    return voiced[0] * 20, (voiced[-1] + 1) * 20


def test_labels_match_the_voiced_audio_in_clean_clips():
    assert clip("dev_single_01")["labels"]["speech"][0][0] == 1000  # 1.0 s of added padding
    for c in fixtures.load_manifest()["clips"]:
        if c["category"] in ("single", "slow_0_8x"):
            assert voiced_bounds_ms(ROOT / "fixtures/audio" / c["file"]) == tuple(c["labels"]["speech"][0]), c["id"]


def test_mid_pause_clips_have_a_first_part_of_at_least_1500_ms_and_a_600_ms_gap():
    for c in fixtures.load_manifest()["clips"]:
        if c["category"] == "mid_pause_600ms":
            (a0, a1), (b0, _) = c["labels"]["speech"]
            assert a1 - a0 >= 1500 and b0 - a1 == 600, c["id"]


def test_every_category_exists_in_both_splits():
    m = fixtures.load_manifest()
    cats = {s: {c["category"] for c in m["clips"] if c["split"] == s} for s in ("dev", "holdout")}
    expected = {"silence", "single", "noisy_10db", "noisy_5db", "slow_0_8x", "mid_pause_600ms", "interrupt", "echo_only"}
    assert cats["dev"] == expected and cats["holdout"] == expected


def test_echo_and_interrupt_clips_reference_an_agent_track():
    m = fixtures.load_manifest()
    agents = {c["id"]: c["category"] for c in m["clips"] if c["category"].startswith("agent_")}
    for c in m["clips"]:
        if c["category"] in ("interrupt", "echo_only"):
            assert agents.get(c["playout_ref"]["clip"]) == f"agent_{c['split']}", c["id"]
            if c["category"] == "interrupt":
                assert c["labels"]["user_onset_ms"] == c["labels"]["speech"][0][0], c["id"]


ANSWER_KEY = ROOT / "fixtures/docs/answer_key.json"
SNAPSHOT = ROOT / "fixtures/docs/uv"


def section(path, heading):
    """Text from `heading` to the next heading of the same or higher level (ignoring fenced code)."""
    lines, out, level, fenced = path.read_text().splitlines(), None, None, False
    for line in lines:
        if line.lstrip().startswith(("```", "~~~")):
            fenced = not fenced
        hashes = len(line) - len(line.lstrip("#"))
        is_heading = not fenced and 0 < hashes <= 6 and line[hashes:hashes + 1] == " "
        if out is not None and is_heading and hashes <= level:
            break
        if out is not None:
            out.append(line)
        elif is_heading and line[hashes:].strip() == heading:
            out, level = [], hashes
    assert out is not None, f"heading {heading!r} not in {path}"
    return "\n".join(out).lower()


def test_answer_key_cites_sections_that_exist_and_contain_the_key_terms():
    questions = json.loads(ANSWER_KEY.read_text())["questions"]
    corpus = "\n".join(p.read_text() for p in SNAPSHOT.rglob("*.md")).lower()
    assert len(questions) == 40 and len({q["id"] for q in questions}) == 40
    assert sum(q["answerable"] for q in questions) == 30
    assert sum(q["split"] == "dev" for q in questions) == 25
    assert sum(bool(q.get("user_record")) and q["split"] == "holdout" for q in questions) == 10
    for q in questions:
        if q["answerable"]:
            text = " ".join(section(SNAPSHOT / c["file"], c["heading"]) for c in q["must_cite"])
            for term in q["must_contain"]:
                assert term.lower() in text, (q["id"], term)
        else:
            for term in q["absent_terms"]:
                assert term.lower() not in corpus, (q["id"], term)


def test_every_docs_question_has_local_audio_in_a_split_specific_voice():
    local = ROOT / "fixtures/audio/local/manifest.json"
    if not local.exists():
        pytest.skip("local-only clips not built (Aura TTS, gitignored): uv run python harness/build_local_fixtures.py")
    clips = json.loads(local.read_text())["clips"]
    tts = {c["question_id"]: c for c in clips if c["voice"] != "user"}
    for q in json.loads(ANSWER_KEY.read_text())["questions"]:
        c = tts[q["id"]]
        assert c["split"] == q["split"]
        assert hashlib.sha256((ROOT / "fixtures/audio" / c["file"]).read_bytes()).hexdigest() == c["sha256"]
    assert {c["voice"] for c in tts.values() if c["split"] == "dev"}.isdisjoint(
        {c["voice"] for c in tts.values() if c["split"] == "holdout"})
