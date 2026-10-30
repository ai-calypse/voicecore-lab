"""WSS runner adapter (seam 9b): headless SDK clients through the real gateway and orchestrator, real time.

    uv run python harness/runner/wss.py --clips dev_single_01 [--providers mock|live] [--parallel N] [--out DIR]

Starts the Go gateway and the Python orchestrator (unless --no-stack), runs one headless client per
clip (or N copies of one clip), then stops the stack. Not deterministic: benchmarks only, not CI gates.
Writes DIR/clients/*.jsonl (client logs) and DIR/traces/*.jsonl (orchestrator traces).
"""
import argparse
import json
import os
import shutil
import signal
import subprocess
import sys
import time
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fixtures import MANIFEST, ROOT, load_manifest  # noqa: E402

CLIENT = ROOT / "packages/web-sdk/bin/headless-client.ts"
GATEWAY = ROOT / "services/realtime-gateway"


def wait_http(url, timeout=60):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        try:
            urllib.request.urlopen(url, timeout=1)
            return
        except Exception:
            time.sleep(0.2)
    raise TimeoutError(url)


def start_stack(providers, trace_dir, logs):
    go = shutil.which("go")
    binary = ROOT / ".cache/bin/gateway"  # never inside the run folder: that folder is committed evidence
    subprocess.run([go, "build", "-o", str(binary), "./cmd/gateway"], cwd=GATEWAY, check=True)
    procs = [
        subprocess.Popen([sys.executable, "-m", "voicecore.server", "--providers", providers, "--trace-dir", str(trace_dir)],
                         cwd=ROOT, stdout=open(logs / "orchestrator.log", "w"), stderr=subprocess.STDOUT),
        subprocess.Popen([str(binary), "-addr", "127.0.0.1:8080", "-upstream", "ws://127.0.0.1:8765"],
                         stdout=open(logs / "gateway.log", "w"), stderr=subprocess.STDOUT),
    ]
    wait_http("http://127.0.0.1:8080/debug/counters")
    time.sleep(1)  # orchestrator loads the VAD model
    return procs


def run_clients(clips, out_dir, tail_s, text=None):
    out_dir.mkdir(parents=True, exist_ok=True)
    procs = []
    for i, c in enumerate(clips):
        log = out_dir / f"{i:02d}_{c['id']}.jsonl"
        cmd = ["node", str(CLIENT), "--fixture", str(MANIFEST.parent / c["file"]), "--out", str(log), "--tail", str(tail_s)]
        procs.append((log, subprocess.Popen(cmd, cwd=ROOT)))
    for _, p in procs:
        p.wait(timeout=600)
    return [log for log, _ in procs]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--clips", nargs="+", default=["dev_single_01"])
    ap.add_argument("--parallel", type=int, default=1, help="copies of each clip, all at once")
    ap.add_argument("--providers", choices=["mock", "live"], default="mock")
    ap.add_argument("--tail", type=float, default=12)
    ap.add_argument("--out", type=Path)
    ap.add_argument("--no-stack", action="store_true")
    args = ap.parse_args()
    run = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    out = args.out or ROOT / f"benchmarks/raw/wss_{args.providers}_{run}"
    (out / "traces").mkdir(parents=True, exist_ok=True)
    by_id = {c["id"]: c for c in load_manifest()["clips"]}
    clips = [by_id[c] for c in args.clips for _ in range(args.parallel)]
    procs = [] if args.no_stack else start_stack(args.providers, out / "traces", out)
    try:
        logs = run_clients(clips, out / "clients", args.tail)
        if procs:
            (out / "gateway_counters.json").write_text(urllib.request.urlopen("http://127.0.0.1:8080/debug/counters").read().decode())
    finally:
        for p in procs:
            p.send_signal(signal.SIGINT)
        for p in procs:
            try:
                p.wait(timeout=15)
            except subprocess.TimeoutExpired:
                p.kill()
    for log in logs:
        events = [json.loads(line) for line in log.read_text().splitlines()]
        print(log.name, [e["type"] for e in events if e["type"] in ("welcome", "agent.generation_started", "playout.started", "playout.stopped", "agent.cancel")])
    print(out)


if __name__ == "__main__":
    main()
