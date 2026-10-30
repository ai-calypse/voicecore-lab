"""Eval gate for CI (S06-T06, seam 9a): uv run python harness/gate.py [--write-baseline]

Runs a fixed in-process scenario set on fake time (real Silero VAD, runtime and echo gate; mock providers),
compares the metrics with harness/thresholds.json and exits 1 on any regression.
"""
import argparse
import json
import sys

import looptime
from bench import turn
from fixtures import ROOT, SPEECH_CATEGORIES, load_manifest
from runner.chaos import SCENARIOS, run_scenario, verify
from runner.inprocess import run_barge_in, run_clip
from timeline import percentile

THRESHOLDS = ROOT / "harness/thresholds.json"
WORST = 10**9  # an empty result fails the latency thresholds instead of crashing the gate


async def measure() -> dict:
    clips = load_manifest()["clips"]
    turns = [turn(await run_clip(c), c) for c in clips if c["split"] == "dev" and c["category"] in SPEECH_CATEGORIES]
    totals = [t["total_ms"] for t in turns if t and t["total_ms"] is not None]
    barge = [await run_barge_in(c, clips=clips) for c in clips if c["split"] == "dev" and c["category"] in ("interrupt", "echo_only")]
    silence = [r["interrupt_to_silence_ms"] for r in barge if r["onset_ms"] is not None]
    chaos = []  # every chaos scenario with literal expectations must meet them
    for path in sorted((SCENARIOS / "chaos").glob("*.json")):
        if "expect" in (scenario := json.loads(path.read_text())):
            chaos += verify(scenario, await run_scenario(path))
    for f in chaos:
        print("CHAOS:", f)
    return {"turns": len(turns), "answered": len(totals), "early_cutoffs": sum(bool(t and t["early"]) for t in turns),
            "total_ms_p50": percentile(totals, 50) if totals else WORST, "total_ms_p95": percentile(totals, 95) if totals else WORST,
            "interrupts_silenced": sum(x is not None for x in silence),
            "interrupt_to_silence_ms_max": max((x for x in silence if x is not None), default=WORST),
            "false_barge_ins": sum(r["barge_in_ms"] is not None for r in barge if r["onset_ms"] is None),
            "chaos_failures": len(chaos)}


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
