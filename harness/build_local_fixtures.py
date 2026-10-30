"""Build the local-only docs-question clips (S00-T03); they are gitignored, never committed.

    uv run python harness/build_local_fixtures.py
    uv run python harness/build_local_fixtures.py --key fixtures/docs/voicecore_key.json   # live load clips vc_a01...

Speaks every answer-key question with Deepgram Aura-2 (dev and holdout use different voices)
and processes the user's own recordings from fixtures/audio/local/raw/user_qNN.wav. Aura output
is kept local because its redistribution terms were not confirmed. Spends from the usd pool.
"""
import json
import sys
import urllib.request
from pathlib import Path

import numpy as np

from baseline_deepgram import load_key
from build_fixtures import OUT, PAD_START_MS, decode, ms, pad, trim, write
from voicecore import budget

VOICES = {"dev": "aura-2-apollo-en", "holdout": "aura-2-luna-en"}
PRICE_PER_CHAR = 0.030 / 1000  # Aura-2 pay as you go, https://deepgram.com/pricing, checked 2026-10-29
LOCAL = OUT / "local"


def speak(text, voice, key):
    req = urllib.request.Request(
        f"https://api.deepgram.com/v1/speak?model={voice}&encoding=linear16&sample_rate=16000&container=none",
        data=json.dumps({"text": text}).encode(), method="POST",
        headers={"Authorization": f"Token {key}", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return np.frombuffer(r.read(), dtype=np.int16), int(r.headers.get("dg-char-count", len(text)))


def entry(q, rel, speech, voice):
    pcm, end = pad(speech), PAD_START_MS + ms(len(speech))
    return {"id": f"{q['split']}_{rel.rsplit('/', 1)[-1][:-4]}", "file": rel, "sha256": write(rel, pcm), "split": q["split"],
            "category": "docs_question", "question_id": q["id"], "voice": voice, "duration_ms": ms(len(pcm)),
            "labels": {"speech": [[PAD_START_MS, end]], "turn_end_ms": end},
            "committed": False}


def voicecore_clips(key_path, speak_fn=speak, api_key=None) -> dict:
    """The answer questions of a VoiceCore answer key (cases, one turn each) as local clips vc_a01... in the dev voice,
    for the live load test. Own folder and manifest, so ids never collide with the docs-question clips."""
    cases = [c for c in json.loads(Path(key_path).read_text())["cases"] if c["expect"] == "answer"]
    out = LOCAL / "voicecore"
    manifest_path = out / "manifest.json"
    clips = {c["id"]: c for c in json.loads(manifest_path.read_text())["clips"]} if manifest_path.exists() else {}

    def save():  # after every clip, so a failure never loses audio that was already paid for
        out.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(json.dumps({"version": 1, "clips": sorted(clips.values(), key=lambda c: c["id"])}, indent=2) + "\n")

    todo = [c for c in cases if f"vc_{c['id']}" not in clips]
    if todo:
        key = api_key or load_key()
        chars = sum(len(c["turns"][0]) for c in todo)
        res = budget.reserve("usd", round(chars * PRICE_PER_CHAR * 1.2, 4), label=f"aura voicecore clips {len(todo)} questions")
        used = 0
        try:
            for c in todo:
                pcm, n = speak_fn(c["turns"][0], VOICES["dev"], key)
                used += n
                e = entry({"split": "dev", "id": c["id"]}, f"local/voicecore/{c['id']}.wav", trim(pcm), VOICES["dev"])
                clips[f"vc_{c['id']}"] = {**e, "id": f"vc_{c['id']}", "category": "voicecore_question"}
                save()
        finally:
            budget.settle(res, round(used * PRICE_PER_CHAR, 6), chars=used, provider="deepgram aura-2")
    save()
    return clips


def main():
    if sys.argv[1:2] == ["--key"]:
        clips = voicecore_clips(sys.argv[2])
        print(f"{len(clips)} VoiceCore clips; usd pool total ${budget.total('usd')}")
        return
    questions = json.loads((OUT.parent / "docs/answer_key.json").read_text())["questions"]
    manifest_path = LOCAL / "manifest.json"
    clips = {c["id"]: c for c in json.loads(manifest_path.read_text())["clips"]} if manifest_path.exists() else {}

    def save():  # after every clip, so a failure never loses audio that was already paid for
        LOCAL.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(json.dumps({"version": 1, "clips": sorted(clips.values(), key=lambda c: c["id"])}, indent=2) + "\n")

    todo = [q for q in questions if f"{q['split']}_docs_question_{q['id']}" not in clips]
    if todo:
        key = load_key()
        chars = sum(len(q["question"]) for q in todo)
        res = budget.reserve("usd", round(chars * PRICE_PER_CHAR * 1.2, 4), label=f"aura fixtures {len(todo)} questions")
        used = 0
        try:
            for q in todo:
                voice = VOICES[q["split"]]
                pcm, n = speak(q["question"], voice, key)
                used += n
                c = entry(q, f"local/{q['split']}/docs_question_{q['id']}.wav", trim(pcm), voice)
                clips[c["id"]] = c
                save()
        finally:
            budget.settle(res, round(used * PRICE_PER_CHAR, 6), chars=used, provider="deepgram aura-2")
    for q in questions:
        raw = LOCAL / "raw" / f"user_{q['id']}.wav"
        if q.get("user_record") and raw.exists():
            c = entry(q, f"local/holdout/user_{q['id']}.wav", trim(decode(raw)), "user")
            clips[c["id"]] = c
    save()
    print(f"{len(clips)} local clips; usd pool total ${budget.total('usd')}")


if __name__ == "__main__":
    main()
