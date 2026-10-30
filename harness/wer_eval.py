"""STT word error rate on holdout audio (S06-T05, live Deepgram): uv run python harness/wer_eval.py

Holdout LibriSpeech clips (single, noisy, slow, mid-pause; reference = LibriSpeech transcript) and holdout
docs questions (Aura voice, local only; reference = the question text). Audio is streamed faster than real
time and closed with CloseStream. Spend is reserved first. Writes reports/wer_holdout.json.
"""
import asyncio
import json
import re
from datetime import UTC, datetime

import jiwer
from fixtures import MANIFEST, ROOT, load_manifest, read_pcm

from voicecore import budget
from voicecore.providers.base import Final
from voicecore.providers.deepgram_stt import PRICE_PER_MIN
from voicecore.providers.factory import make_live

CATEGORIES = ("single", "noisy_10db", "noisy_5db", "slow_0_8x", "mid_pause_600ms")


def norm(t: str) -> str:
    """Lowercase, letters/digits/apostrophes only, single spaces; 'u v' and 'you v' are not merged (that would hide errors)."""
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9' ]", " ", t.lower().replace("-", " "))).strip()


async def transcribe(res, pcm):
    stt = make_live("stt", res)
    for i in range(0, len(pcm), 320):  # real-time pacing: streamed faster, Deepgram dropped the end of clips on close
        await stt.send(pcm[i : i + 320].tobytes())
        await asyncio.sleep(0.02)
    await stt.close()
    text = " ".join(e.text for e in [e async for e in stt.events()] if isinstance(e, Final))
    return text, stt.cost_usd()


async def main():
    clips = [c for c in load_manifest()["clips"] if c["split"] == "holdout" and c["category"] in CATEGORIES]
    key = {q["id"]: q["question"] for q in json.loads((ROOT / "fixtures/docs/answer_key.json").read_text())["questions"]}
    local = MANIFEST.parent / "local/manifest.json"
    docs = [c for c in load_manifest(local)["clips"] if c["split"] == "holdout"] if local.exists() else []
    run = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    seconds = sum(c["duration_ms"] for c in clips + docs) / 1000
    res = budget.reserve("usd", round(seconds / 60 * PRICE_PER_MIN * 1.2, 6), label=f"wer_eval {run}")
    rows, spent = [], 0.0
    try:
        for c in clips + docs:
            ref = c.get("transcript") or key[c["question_id"]]
            hyp, cost = await transcribe(res, read_pcm(c))
            spent += cost
            rows.append({"clip": c["id"], "category": c["category"], "ref": norm(ref), "hyp": norm(hyp)})
    finally:
        budget.settle(res, round(spent, 6), run_id=run)
    def wer(rs):
        return jiwer.wer([r["ref"] for r in rs], [r["hyp"] for r in rs]) if rs else None
    by_cat = {cat: round(wer([r for r in rows if r["category"] == cat]), 4) for cat in sorted({r["category"] for r in rows})}
    out = {"run_id": run, "model": "deepgram nova-3 (keyterms: uv, uvx, uv sync, uv lock, pyproject.toml)", "wer_all": round(wer(rows), 4),
           "wer_by_category": by_cat, "clips": len(rows), "audio_s": seconds, "cost_usd": round(spent, 6), "rows": rows}
    (ROOT / "reports/wer_holdout.json").write_text(json.dumps(out, indent=2) + "\n")
    print(json.dumps({k: v for k, v in out.items() if k != "rows"}, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
