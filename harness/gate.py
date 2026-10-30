"""Eval gate for CI (S06-T06, seam 9a): uv run python harness/gate.py [--write-baseline]

Runs a fixed in-process scenario set on fake time (real Silero VAD, runtime and echo gate; mock providers),
compares the metrics with harness/thresholds.json and exits 1 on any regression.
"""
import argparse
import json
import sys

import looptime
from bench import turn
from fixtures import ROOT, load_manifest
from runner.inprocess import run_barge_in, run_clip
from timeline import percentile

THRESHOLDS = ROOT / "harness/thresholds.json"
CATEGORIES = ("single", "noisy_10db", "noisy_5db", "slow_0_8x", "mid_pause_600ms")


async def measure() -> dict:
    clips = load_manifest()["clips"]
    turns = [turn(await run_clip(c), c) for c in clips if c["split"] == "dev" and c["category"] in CATEGORIES]
    totals = [t["total_ms"] for t in turns if t and t["total_ms"] is not None]
    barge = [await run_barge_in(c, clips=clips) for c in clips if c["split"] == "dev" and c["category"] in ("interrupt", "echo_only")]
    silence = [r["interrupt_to_silence_ms"] for r in barge if r["onset_ms"] is not None]
    return {"turns": len(turns), "answered": len(totals), "early_cutoffs": sum(bool(t and t["early"]) for t in turns),
            "total_ms_p50": percentile(totals, 50), "total_ms_p95": percentile(totals, 95),
            "interrupts_silenced": sum(x is not None for x in silence), "interrupt_to_silence_ms_max": max(x for x in silence if x is not None),
            "false_barge_ins": sum(r["barge_in_ms"] is not None for r in barge if r["onset_ms"] is None)}


def check(m: dict, t: dict) -> list[str]:
    fails = []
    for k, limit in t["min"].items():
        if m[k] < limit:
            fails.append(f"{k} = {m[k]} < {limit}")
    for k, limit in t["max"].items():
        if m[k] > limit:
            fails.append(f"{k} = {m[k]} > {limit}")
    return fails


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--write-baseline", action="store_true", help="print the measured metrics (to set thresholds)")
    args = ap.parse_args()
    loop = looptime.new_event_loop()
    m = loop.run_until_complete(measure())
    print(json.dumps(m, indent=2))
    if args.write_baseline:
        return
    fails = check(m, json.loads(THRESHOLDS.read_text()))
    for f in fails:
        print("REGRESSION:", f)
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
