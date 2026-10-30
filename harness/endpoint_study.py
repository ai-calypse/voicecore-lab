"""Endpointing study with live STT (latency work): uv run python harness/endpoint_study.py [--record] [--finalize-ms 200]

--record streams each dev clip to Deepgram in real time with Silero VAD running alongside; after
`finalize_ms` of VAD silence it sends Finalize once per pause, and logs every final with its arrival time
(ms of audio). Without --record it replays the saved log (no spend) through candidate policies and
prints decision delay and early cutoffs against the labelled turn end. Writes reports/endpoint_study.json.
"""
import argparse
import asyncio
import json
import re
import time

from fixtures import MANIFEST, ROOT, SPEECH_CATEGORIES, load_manifest, read_frames
from timeline import percentile

from voicecore import budget
from voicecore.providers.base import Final
from voicecore.providers.deepgram_stt import PRICE_PER_MIN
from voicecore.providers.factory import make_live
from voicecore.turntaking.vad_silero import SileroVAD

LOG = ROOT / "benchmarks/raw/endpoint_study_log.json"
OUT = ROOT / "reports/endpoint_study.json"
PUNCT = re.compile(r"[.?!]\s*$")


def clips():
    local = MANIFEST.parent / "local/manifest.json"
    docs = [c for c in load_manifest(local)["clips"] if c["split"] == "dev"] if local.exists() else []
    return docs + [c for c in load_manifest()["clips"] if c["split"] == "dev" and c["category"] in SPEECH_CATEGORIES]


async def record_clip(res, clip, finalize_ms):
    stt, vad = make_live("stt", res), SileroVAD()
    finals, probs, finalized = [], [], []
    t0 = time.perf_counter()
    now_ms = lambda: (time.perf_counter() - t0) * 1000  # noqa: E731

    async def reader():
        async for e in stt.events():
            if isinstance(e, Final):
                finals.append({"t_ms": round(now_ms()), "text": e.text})

    task = asyncio.create_task(reader())
    silence, speaking = 0, False
    for k, pcm in enumerate(read_frames(clip)):
        await asyncio.sleep(max(0.0, (t0 + (k + 1) * 0.02) - time.perf_counter()))  # frame complete at (k+1) x 20 ms
        p = vad.frame(pcm)
        probs.append(round(p, 3))
        await stt.send(pcm.tobytes())
        if p >= 0.5:
            speaking, silence = True, 0
        elif speaking:
            silence += 20
            if silence == finalize_ms:
                await stt.finalize()
                finalized.append((k + 1) * 20)
    await asyncio.sleep(1.5)  # let late finals arrive
    await stt.close()
    await task
    return {"clip": clip["id"], "category": clip["category"], "turn_end_ms": clip["labels"]["turn_end_ms"],
            "speech": clip["labels"]["speech"], "probs": probs, "finals": finals, "finalize_at_ms": finalized}, stt.cost_usd()


def decide(rec, policy):
    """First endpoint time (ms of audio) under a policy, from the recorded VAD probs and final arrivals."""
    kind, a, b = policy
    silence, speaking, onset = 0, False, None
    for k, p in enumerate(rec["probs"]):
        t = (k + 1) * 20
        if p >= 0.5:
            speaking, silence = True, 0
            continue
        if not speaking:
            continue
        silence += 20
        if kind == "fixed" and silence >= a:
            return t
        if kind == "eager":  # a punctuated final that arrived during this pause, after >= a ms of silence; else fixed b
            start = t - silence
            if silence >= a and any(start <= f["t_ms"] <= t and PUNCT.search(f["text"]) for f in rec["finals"]):
                return t
            if silence >= b:
                return t
    return None


POLICIES = [("fixed", ms, None) for ms in (300, 400, 500, 600, 800)] + \
           [("eager", s, 800) for s in (200, 250, 300, 400)] + [("eager", s, 600) for s in (200, 250, 300)]


def evaluate(log):
    out = {}
    for pol in POLICIES:
        name = f"{pol[0]}_{pol[1]}" + (f"_else_{pol[2]}" if pol[2] else "")
        rows = []
        for rec in log:
            ep = decide(rec, pol)
            rows.append({"clip": rec["clip"], "cat": rec["category"], "delay": None if ep is None else ep - rec["turn_end_ms"],
                         "early": ep is not None and ep < rec["turn_end_ms"]})
        delays = [r["delay"] for r in rows if r["delay"] is not None and not r["early"]]
        out[name] = {"n": len(rows), "early": sum(r["early"] for r in rows), "early_clips": [r["clip"] for r in rows if r["early"]],
                     "delay_p50": percentile(delays, 50) if delays else None, "delay_p95": percentile(delays, 95) if delays else None,
                     "docs_delay_p50": percentile(d, 50) if (d := [r["delay"] for r in rows if r["cat"] == "docs_question" and r["delay"] is not None and not r["early"]]) else None}
    return out


async def record(finalize_ms):
    cs = clips()
    secs = sum(c["duration_ms"] for c in cs) / 1000
    res = budget.reserve("usd", round(secs / 60 * PRICE_PER_MIN * 1.3, 6), label="endpoint study")
    log, spent = [], 0.0
    try:
        for c in cs:
            rec, cost = await record_clip(res, c, finalize_ms)
            log.append(rec)
            spent += cost
            print(c["id"], len(rec["finals"]), "finals", flush=True)
    finally:
        budget.settle(res, round(spent, 6))
        LOG.write_text(json.dumps({"finalize_ms": finalize_ms, "clips": log}) + "\n")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--record", action="store_true")
    ap.add_argument("--finalize-ms", type=int, default=200)
    a = ap.parse_args()
    if a.record:
        asyncio.run(record(a.finalize_ms))
    data = json.loads(LOG.read_text())
    res = evaluate(data["clips"])
    OUT.write_text(json.dumps({"finalize_ms": data["finalize_ms"], "policies": res}, indent=2) + "\n")
    for k, v in res.items():
        print(f"{k:22s} early {v['early']:2d}/{v['n']}  delay p50 {v['delay_p50']}  p95 {v['delay_p95']}  docs p50 {v['docs_delay_p50']}  {v['early_clips'][:4]}")
