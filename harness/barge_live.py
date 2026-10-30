"""Interruption benchmark, live providers (S05-T04): uv run python harness/barge_live.py [--interrupts 16] [--echo-only 4]

Each script: the headless client asks a question by text, plays the live answer, hears its own playback in
its mic (-15 dB, 40 ms: a simulated room), and 1.2 s into playback starts a user clip that interrupts.
Echo-only scripts never interrupt: any cancel there is a false barge-in. Runs one at a time (Cartesia limits
concurrent requests). Writes benchmarks/raw/barge_live_<run>/ and prints the summary.
"""
import argparse
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import MANIFEST, ROOT, load_manifest  # noqa: E402
from runner.wss import CLIENT, start_stack  # noqa: E402
from timeline import percentile  # noqa: E402

QUESTION = "How do I start a new project with uv and add a dependency to it?"
USERS = ["dev_single_01", "dev_single_02", "dev_single_03", "dev_single_04", "dev_noisy_10db_01", "dev_noisy_10db_02",
         "dev_slow_0_8x_01", "dev_slow_0_8x_02"]


def client(out, clip=None, tail=2):
    cmd = ["node", str(CLIENT), "--text", QUESTION, "--echo-db=-15", "--out", str(out), "--tail", str(tail)]
    if clip:
        cmd += ["--fixture", str(MANIFEST.parent / clip["file"]), "--interrupt-after", "1200",
                "--onset-ms", str(clip["labels"]["speech"][0][0]), "--exit-after-cancel-ms", "1500"]
    subprocess.run(cmd, cwd=ROOT, timeout=120, check=False)
    return [json.loads(line) for line in out.read_text().splitlines()]


def score(events):
    onset = next((e["onset_us"] for e in events if e["type"] == "user.onset"), None)
    stop = next((e for e in events if e["type"] == "playout.stopped" and e.get("dir") == "out"), None)
    heard = next((e["t_us"] for e in events if e["type"] == "user.speech_started" and e.get("dir") == "in"), None)
    return {"cancelled": any(e["type"] == "agent.cancel" for e in events), "stopped": stop and stop["reason"],
            "interrupt_to_silence_ms": round((stop["t_us"] - onset) / 1000, 1) if onset and stop and stop["reason"] == "cancel" else None,
            "interrupt_to_listening_ms": round((heard - onset) / 1000, 1) if onset and heard else None,
            "played": any(e["type"] == "playout.started" for e in events)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--interrupts", type=int, default=16)
    ap.add_argument("--echo-only", type=int, default=4)
    args = ap.parse_args()
    run = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    out = ROOT / f"benchmarks/raw/barge_live_{run}"
    (out / "clients").mkdir(parents=True)
    by_id = {c["id"]: c for c in load_manifest()["clips"]}
    procs = start_stack("live", out / "traces", out)
    rows = []
    try:
        for i in range(args.interrupts):
            c = by_id[USERS[i % len(USERS)]]
            rows.append({"script": i, "kind": "interrupt", "user": c["id"], **score(client(out / f"clients/{i:02d}_interrupt.jsonl", c))})
            print(rows[-1], flush=True)
        for j in range(args.echo_only):
            i = args.interrupts + j
            rows.append({"script": i, "kind": "echo_only", **score(client(out / f"clients/{i:02d}_echo_only.jsonl", tail=14))})
            print(rows[-1], flush=True)
    finally:
        for p in procs:
            p.send_signal(2)
        for p in procs:
            p.wait(timeout=20)
    hits = [r for r in rows if r["kind"] == "interrupt"]
    xs = [r["interrupt_to_silence_ms"] for r in hits if r["interrupt_to_silence_ms"] is not None]
    ls = [r["interrupt_to_listening_ms"] for r in hits if r["interrupt_to_listening_ms"] is not None]
    summary = {"interrupts": len(hits), "silenced": len(xs), "silence_p50": xs and percentile(xs, 50),
               "silence_p95": xs and percentile(xs, 95), "listening_p50": ls and percentile(ls, 50),
               "false_barge_ins": f"{sum(r['cancelled'] for r in rows if r['kind'] == 'echo_only')}/{args.echo_only}"}
    (out / "summary.json").write_text(json.dumps({"summary": summary, "rows": rows}, indent=2) + "\n")
    print(json.dumps(summary, indent=2))
    print(out)


if __name__ == "__main__":
    main()
