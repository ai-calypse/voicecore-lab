"""Mock load through the scale profile (Step 09 Phase 10): uv run python harness/load.py --parallel 20 [--copies 1|2]

N headless clients stream a labelled clip through the load balancer at once (real audio, real VAD, mock providers).
Reports how many got an answer, and from the orchestrators' own metrics (the change during this run): server
endpoint-to-first-audio p95, event-loop lag p99, and each container's CPU and memory. Numbers are `fake-provider`.
"""
import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "harness"))
from runner.wss import all_clips, run_clients  # noqa: E402

ORCHS = ("orch-1", "orch-2")


def compose(*args) -> str:
    return subprocess.run(["docker", "compose", "--profile", "scale", *args], cwd=ROOT, check=True, capture_output=True, text=True).stdout


def buckets(orch: str, metric: str, labels: str = "") -> dict[float, float]:
    py = "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:9464/metrics').read().decode())"
    body = compose("exec", "-T", orch, "/app/.venv/bin/python", "-c", py)
    out = {}
    for le, v in re.findall(rf'^{metric}_bucket\{{([^}}]*)\}} ([0-9.e+]+)$', body, re.M):
        if labels in le:
            b = float(re.search(r'le="([^"]+)"', le).group(1))  # float() reads "+Inf" too
            out[b] = out.get(b, 0) + float(v)
    return out


def quantile(q: float, before: dict, after: dict) -> float | None:
    """Prometheus histogram_quantile over the change between two snapshots (linear within the bucket)."""
    bounds = sorted(after)
    counts = [after[b] - before.get(b, 0) for b in bounds]
    total = counts[-1] if counts else 0
    if not total:
        return None
    rank, prev_b, prev_c = q * total, 0.0, 0.0
    for b, c in zip(bounds, counts):
        if c >= rank:
            return prev_b if b == float("inf") else prev_b + (b - prev_b) * (rank - prev_c) / max(c - prev_c, 1e-9)
        prev_b, prev_c = b, c
    return None


def merged(snapshots: list[dict]) -> dict:
    out: dict[float, float] = {}
    for snap in snapshots:
        for k, v in snap.items():
            out[k] = out.get(k, 0) + v
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--parallel", type=int, required=True)
    ap.add_argument("--copies", type=int, choices=[1, 2], default=2,
                    help="orchestrator copies; 1 stops orch-2 for the run (both gateways stay: nginx does not retry a POST to a dead one)")
    ap.add_argument("--clip", default="dev_single_01")
    ap.add_argument("--out", type=Path, default=ROOT / "benchmarks/raw/load")
    args = ap.parse_args()
    live = ORCHS[:args.copies]
    if args.copies == 1:
        compose("stop", "-t", "30", "orch-2")
    try:
        stage = 'stage="endpoint_to_first_audio"'
        before = [(buckets(o, "voicecore_stage_ms", stage), buckets(o, "voicecore_event_loop_lag_ms")) for o in live]
        clip = next(c for c in all_clips() if c["id"] == args.clip)
        logs = run_clients([clip] * args.parallel, args.out / f"n{args.parallel}_c{args.copies}", 12, gateway="http://127.0.0.1:8090")
        after = [(buckets(o, "voicecore_stage_ms", stage), buckets(o, "voicecore_event_loop_lag_ms")) for o in live]
        answered = sum(any(json.loads(line)["type"] == "playout.started" for line in log.read_text().splitlines()) for log in logs)
        stats = subprocess.run(["docker", "stats", "--no-stream", "--format", "{{.Name}} {{.CPUPerc}} {{.MemUsage}}"],
                               capture_output=True, text=True).stdout
        row = {"label": "fake-provider", "parallel": args.parallel, "copies": args.copies, "answered": answered,
               "endpoint_to_first_audio_p95_ms": quantile(0.95, merged([b[0] for b in before]), merged([a[0] for a in after])),
               "loop_lag_p99_ms": max((quantile(0.99, b[1], a[1]) or 0) for b, a in zip(before, after)),
               "containers": [line for line in stats.splitlines() if any(n in line for n in ("orch-", "gw-", "lb-", "redis-"))]}
        print(json.dumps(row, indent=1))
    finally:
        if args.copies == 1:
            compose("up", "-d", "--wait", "orch-2")


if __name__ == "__main__":
    main()
