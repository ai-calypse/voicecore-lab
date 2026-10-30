"""Soak (Step 09 Phase 10): uv run python harness/soak.py [--minutes 30] against the scale profile.

Ten clients stream a labelled clip through the load balancer, again and again, for the whole run. Every minute it
records each container's memory, the gateways' goroutines and open files, and Redis's memory. A leak shows as
growth from the first sample to the last; the pass rule is under 10% per process, with goroutines and files flat.
"""
import argparse
import json
import re
import subprocess
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "harness"))
from runner.wss import all_clips, run_clients  # noqa: E402


def compose(*args) -> str:
    return subprocess.run(["docker", "compose", "--profile", "scale", *args], cwd=ROOT, check=True, capture_output=True, text=True).stdout


def mib(s: str) -> float:
    n, unit = re.match(r"([0-9.]+)\s*([KMG]i?B)", s).groups()
    return float(n) * {"KiB": 1 / 1024, "MiB": 1, "GiB": 1024, "KB": 1 / 1000, "MB": 1, "GB": 1000}[unit]


def sample() -> dict:
    stats = subprocess.run(["docker", "stats", "--no-stream", "--format", "{{.Name}}\t{{.MemUsage}}"], capture_output=True, text=True).stdout
    mem = {m.group(1): round(mib(use.split("/")[0]), 1)
           for name, use in (line.split("\t") for line in stats.splitlines())
           if (m := re.search(r"-(orch-\d|gw-\d|redis|lb)-\d+$", name))}
    out = {"t": round(time.time()), "mem_mib": mem}
    for gw in ("gw-1", "gw-2"):
        body = compose("exec", "-T", "lb", "wget", "-qO-", f"http://{gw}:9091/metrics")
        out[gw] = {k: float(re.search(rf"^{k} ([0-9.e+]+)$", body, re.M).group(1)) for k in ("go_goroutines", "process_open_fds")}
    out["redis_used_mib"] = round(int(re.search(r"used_memory:(\d+)", compose("exec", "-T", "redis", "redis-cli", "INFO", "memory")).group(1)) / 2**20, 2)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--minutes", type=float, default=30)
    ap.add_argument("--out", type=Path, default=ROOT / "benchmarks/raw/soak")
    args = ap.parse_args()
    clip = next(c for c in all_clips() if c["id"] == "dev_single_01")
    stop, rounds, errors = time.time() + args.minutes * 60, [0], []

    def load():  # a failed round is recorded, never fatal: an idle stack would otherwise pass for a leak-free one
        while time.time() < stop:
            try:
                run_clients([clip] * 10, args.out / "clients", 5, gateway="http://127.0.0.1:8090")
                rounds[0] += 1
            except Exception as e:  # noqa: BLE001
                errors.append(f"{type(e).__name__}: {e}"[:200])
                time.sleep(5)

    t = threading.Thread(target=load, daemon=True)
    t.start()
    samples = []
    while time.time() < stop:
        try:
            samples.append(sample())
            print(json.dumps(samples[-1]), flush=True)
        except Exception as e:  # noqa: BLE001
            errors.append(f"sample: {type(e).__name__}: {e}"[:200])
        time.sleep(60)
    t.join()
    samples.append(sample())
    # warm-up: a gateway's heap grows for its first ~5 minutes under load, then levels off (seen 2026-10-30)
    first, last = samples[min(5, len(samples) - 2)] if len(samples) > 2 else samples[0], samples[-1]
    growth = {k: round(100 * (last["mem_mib"][k] - v) / v, 1) for k, v in first["mem_mib"].items() if k in last["mem_mib"] and v}
    print(json.dumps({"label": "fake-provider", "minutes": args.minutes, "rounds_of_10": rounds[0], "load_errors": errors, "mem_growth_pct": growth,
                      "goroutines": {g: (first[g]["go_goroutines"], last[g]["go_goroutines"]) for g in ("gw-1", "gw-2")},
                      "open_fds": {g: (first[g]["process_open_fds"], last[g]["process_open_fds"]) for g in ("gw-1", "gw-2")},
                      "redis_used_mib": (first["redis_used_mib"], last["redis_used_mib"])}, indent=1))


if __name__ == "__main__":
    main()
