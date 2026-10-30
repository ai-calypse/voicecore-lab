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
COUNTERS_URL = "http://127.0.0.1:8080/debug/counters"  # the gateway start_stack launches
ORCH_READY_URL = "http://127.0.0.1:8765/readyz"  # 503 until the VAD and docs index are loaded
GATEWAY = ROOT / "services/realtime-gateway"


def wait_http(url, timeout=60, alive=None):
    """Poll url until it answers 2xx/3xx. alive: a Popen that must still run (a crashed or port-clashing process
    fails fast instead of after the timeout)."""
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if alive is not None and alive.poll() is not None:
            raise RuntimeError(f"{url}: its process exited with {alive.returncode}")
        try:
            urllib.request.urlopen(url, timeout=1)
            return
        except Exception:
            time.sleep(0.2)
    raise TimeoutError(url)


def start_stack(providers, trace_dir, logs, policy="fixed", server_args=()):
    go = shutil.which("go")
    binary = ROOT / ".cache/bin/gateway"  # never inside the run folder: that folder is committed evidence
    subprocess.run([go, "build", "-o", str(binary), "./cmd/gateway"], cwd=GATEWAY, check=True)
    procs = [
        subprocess.Popen([sys.executable, "-m", "voicecore.server", "--providers", providers, "--trace-dir", str(trace_dir), "--policy", policy, *server_args],
                         cwd=ROOT, stdout=open(logs / "orchestrator.log", "w"), stderr=subprocess.STDOUT),
        # all benchmark clients share one IP: lift the per-IP abuse limits for this local run only
        subprocess.Popen([str(binary), "-addr", "127.0.0.1:8080", "-upstream", "ws://127.0.0.1:8765", "-trace", str(logs / "gateway_trace.jsonl"),
                          "-max-sessions-per-ip", "0", "-tokens-per-minute", "0"],
                         stdout=open(logs / "gateway.log", "w"), stderr=subprocess.STDOUT),
    ]
    wait_http(COUNTERS_URL)
    wait_http(ORCH_READY_URL, timeout=600, alive=procs[0])  # it serves at once but loads models before taking sessions
    if any(p.poll() is not None for p in procs):  # e.g. a docker stack already holds :8080 and would answer instead
        for p in procs:
            p.kill()
        sys.exit(f"stack failed to start: see {logs}/gateway.log and orchestrator.log")
    return procs


def run_clients(clips, out_dir, tail_s, sequential=False):
    out_dir.mkdir(parents=True, exist_ok=True)
    procs = []
    for i, c in enumerate(clips):
        log = out_dir / f"{i:02d}_{c['id']}.jsonl"
        cmd = ["node", str(CLIENT), "--fixture", str(MANIFEST.parent / c["file"]), "--out", str(log), "--tail", str(tail_s)]
        procs.append((log, subprocess.Popen(cmd, cwd=ROOT)))
        if sequential:
            procs[-1][1].wait(timeout=600)
    for _, p in procs:
        p.wait(timeout=600)
    return [log for log, _ in procs]


def all_clips():
    """Committed clips plus the local-only docs-question clips when present."""
    clips = load_manifest()["clips"]
    local = MANIFEST.parent / "local/manifest.json"
    return clips + (load_manifest(local)["clips"] if local.exists() else [])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--clips", nargs="+", default=["dev_single_01"])
    ap.add_argument("--parallel", type=int, default=1, help="copies of each clip, all at once")
    ap.add_argument("--providers", choices=["mock", "live"], default="mock")
    ap.add_argument("--tail", type=float, default=12)
    ap.add_argument("--out", type=Path)
    ap.add_argument("--no-stack", action="store_true")
    ap.add_argument("--sequential", action="store_true", help="one client at a time (provider concurrency limits)")
    ap.add_argument("--policy", choices=["fixed", "adaptive", "asr_assisted", "eager"], help="default: the orchestrator's (eager live, fixed mock)")
    ap.add_argument("--server-arg", action="append", default=[], help="extra orchestrator flag, e.g. --server-arg=--llm-model=openai/gpt-4.1-nano")
    ap.add_argument("--label", default="", help="suffix for the run folder")
    args = ap.parse_args()
    run = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    args.policy = args.policy or ("eager" if args.providers == "live" else "fixed")
    out = args.out or ROOT / f"benchmarks/raw/wss_{args.providers}_{args.policy}{'_' + args.label if args.label else ''}_{run}"
    (out / "traces").mkdir(parents=True, exist_ok=True)
    by_id = {c["id"]: c for c in all_clips()}
    clips = [by_id[c] for c in args.clips for _ in range(args.parallel)]
    procs = [] if args.no_stack else start_stack(args.providers, out / "traces", out, args.policy, args.server_arg)
    try:
        logs = run_clients(clips, out / "clients", args.tail, args.sequential)
        if procs:
            (out / "gateway_counters.json").write_text(urllib.request.urlopen(COUNTERS_URL).read().decode())
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
