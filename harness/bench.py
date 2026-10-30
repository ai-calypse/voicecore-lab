"""Performance benchmark, fake providers (S06-T04): uv run python harness/bench.py

In-process, fake time, real Silero VAD and runtime; mock STT/LLM/TTS with fixed delays (STT final on
Finalize, LLM first token 200 ms, TTS first audio 150 ms). Every dev speech clip x one-way delay 0/20/50 ms
x clean or 15 dB pink noise x 3 seeds. Writes reports/perf_fake.json.
"""
import json

import looptime
from fixtures import ROOT, SPEECH_CATEGORIES, load_manifest
from runner.inprocess import run_clip
from timeline import percentile


def turn(run, clip):
    """speech end -> first rendered agent sample, and speech end -> endpoint, both on the loop clock (ms)."""
    end = run["t0_us"] + clip["labels"]["turn_end_ms"] * 1000
    gens = [e["gen"] for e in run["client"] if e["type"] == "agent.generation_started"]
    if not gens:
        return None
    started = next((e["t_us"] for e in run["client"] if e["type"] == "playout.started" and e["gen"] == gens[-1]), None)
    ep = [e for e in run["trace"] if e["event"] == "endpoint"]
    return {"clip": clip["id"], "total_ms": (started - end) / 1000 if started else None,
            "endpoint_ms": (ep[-1]["attrs"]["capture_end_us"] - end) / 1000 if ep else None, "early": bool(ep) and ep[0]["attrs"]["capture_end_us"] < end,
            "generations": len(gens)}


async def main():
    clips = [c for c in load_manifest()["clips"] if c["split"] == "dev" and c["category"] in SPEECH_CATEGORIES]
    rows = []
    for seed in (1, 2, 3):
        for net in (0, 20, 50):
            for snr in (None, 15):
                for c in clips:
                    r = await run_clip(c, net_ms=net, snr_db=snr, seed=seed)
                    t = turn(r, c)
                    rows.append({**(t or {"clip": c["id"], "total_ms": None}), "net_ms": net, "snr_db": snr, "seed": seed,
                                 "stt_drops": r["stt_drops"]})
    ok = [r["total_ms"] for r in rows if r.get("total_ms") is not None]
    ep = [r["endpoint_ms"] for r in rows if r.get("endpoint_ms") is not None]
    summary = {"label": "fake-provider", "turns": len(rows), "answered": len(ok),
               "total_ms": {p: percentile(ok, p) if ok else None for p in (50, 95, 99)},
               "endpoint_ms": {p: percentile(ep, p) if ep else None for p in (50, 95, 99)},
               "early_cutoff_turns": sum(bool(r.get("early")) for r in rows), "stt_drops": sum(r["stt_drops"] for r in rows),
               "by_net_ms": {n: percentile(xs, 50) if (xs := [r["total_ms"] for r in rows if r["net_ms"] == n and r.get("total_ms") is not None]) else None
                             for n in (0, 20, 50)}}
    (ROOT / "reports/perf_fake.json").write_text(json.dumps({"summary": summary, "rows": rows}, indent=2) + "\n")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    loop = looptime.new_event_loop()
    loop.run_until_complete(main())
