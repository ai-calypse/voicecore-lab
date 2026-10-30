"""Endpoint policy sweep (S02-T05): uv run python harness/turn_sweep.py [--holdout POLICY]

Real Silero VAD on the dev fixtures, each policy fed the same frames. asr_assisted gets a
simulated STT: a final per labelled speech segment at segment end + 300 ms, ending in ".".
Writes reports/turn_policy.json and reports/turn_policy.png.
"""
import argparse
import json
from dataclasses import replace

from fixtures import ROOT, load_manifest, played_power, read_frames
from timeline import endpoint_scores

from voicecore.turntaking.floor import Floor, Policy, power
from voicecore.turntaking.vad_silero import SileroVAD

CATEGORIES = ("single", "noisy_10db", "noisy_5db", "slow_0_8x", "mid_pause_600ms")
STT_DELAY_MS = 300
POLICIES = {f"fixed_{ms}": Policy("fixed", silence_ms=ms) for ms in (300, 400, 500, 600, 700, 800, 900, 1200)}
POLICIES |= {"adaptive": Policy("adaptive"), "adaptive_800_900_1000": Policy("adaptive", adaptive_ms=(800, 900, 1000)),
             "asr_assisted": Policy("asr_assisted"), "asr_assisted_700": Policy("asr_assisted", asr_silence_ms=700),
             "asr_assisted_700_on_900": Policy("asr_assisted", asr_silence_ms=700, adaptive_ms=(900, 900, 900))}


def probs(clip, cache={}):
    if clip["id"] not in cache:
        vad = SileroVAD()
        cache[clip["id"]] = [vad.frame(f) for f in read_frames(clip)]
    return cache[clip["id"]]


def run(policy, clip, clips=None):
    """Feed one clip through a floor. With clips given, echo/interrupt clips also get the played audio."""
    floor, events = Floor(policy), []
    finals = [(b + STT_DELAY_MS, "segment.") for _, b in clip["labels"]["speech"]]
    ref, playing = played_power(clip, clips) if clips and "playout_ref" in clip else (None, None)
    mic = read_frames(clip)
    for k, p in enumerate(probs(clip)):
        while finals and finals[0][0] <= k * 20:
            finals.pop(0)
            events += floor.transcript_final("segment.")
        if ref is None:
            events += floor.frame(p)
        else:
            events += floor.frame(p, power(mic[k]), ref[k] if playing[k] else None)
    return events


def evaluate(policy, clips, everything):
    turns = [c for c in clips if c["category"] in CATEGORIES]
    cases, failures = [], []
    for c in turns:
        ends = [e.t_ms for e in run(policy, c) if e.kind == "endpoint"]
        cases.append((c["labels"]["turn_end_ms"], ends))
        if not ends or ends[0] < c["labels"]["turn_end_ms"]:
            failures.append({"clip": c["id"], "endpoints_ms": ends, "turn_end_ms": c["labels"]["turn_end_ms"]})
    s = endpoint_scores(cases)
    silence = [c for c in clips if c["category"] == "silence"]
    echo = [c for c in clips if c["category"] == "echo_only"]
    interrupts = [c for c in clips if c["category"] == "interrupt"]
    barge = []
    for c in interrupts:
        first = next((e for e in run(policy, c, everything) if e.kind == "barge_in"), None)
        barge.append(None if first is None else first.t_ms - c["labels"]["user_onset_ms"])
    return {**s, "failures": failures,
            "false_starts_silence": f"{sum(bool(run(policy, c)) for c in silence)}/{len(silence)}",
            "false_barge_ins_echo_only": f"{sum(bool(run(policy, c, everything)) for c in echo)}/{len(echo)}",
            "barge_in_delay_ms": barge}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--holdout", help="run one policy once on the holdout split")
    args = ap.parse_args()
    clips = load_manifest()["clips"]
    if args.holdout:
        res = evaluate(POLICIES[args.holdout], [c for c in clips if c["split"] == "holdout"], clips)
        (ROOT / "reports/turn_policy_holdout.json").write_text(json.dumps({args.holdout: res}, indent=2) + "\n")
        print(json.dumps({k: v for k, v in res.items() if k != "delays_ms"}, indent=2))
        return
    dev = [c for c in clips if c["split"] == "dev"]
    results = {name: evaluate(p, dev, clips) for name, p in POLICIES.items()}
    (ROOT / "reports").mkdir(exist_ok=True)
    (ROOT / "reports/turn_policy.json").write_text(json.dumps(results, indent=2) + "\n")
    for name, r in results.items():
        print(f"{name:24s} median {r['median_ms']} p95 {r['p95_ms']} early {r['early_cutoffs']}/{r['n']} missed {r['missed']} "
              f"silence {r['false_starts_silence']} echo {r['false_barge_ins_echo_only']} barge-in {r['barge_in_delay_ms']}")
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(7, 4.5))
    points = {}
    for name, r in results.items():
        points.setdefault((r["median_ms"], 100 * r["early_cutoff_rate"]), []).append(name)
    for (x, y), names in points.items():
        ax.scatter(x, y, color="#c0392b" if all(n.startswith("fixed") for n in names) else "#2471a3", s=40)
        ax.annotate("\n".join(names), (x, y), textcoords="offset points", xytext=(5, 4), fontsize=8)
    ax.set_xlabel("median endpoint delay after labelled turn end (ms)")
    ax.set_ylabel("early cutoffs (% of turns)")
    ax.set_title(f"Endpoint policies on {results['adaptive']['n']} dev turns (Silero VAD; asr_assisted simulated)")
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(ROOT / "reports/turn_policy.png", dpi=120)


if __name__ == "__main__":
    main()
