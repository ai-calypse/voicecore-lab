"""Monitoring profile, end to end (marked docker: CI job "monitoring", or `make monitoring-test`).

Needs `docker compose --profile monitoring up -d --wait` first. Prometheus and the alert sink are read through
`docker compose exec` and `docker compose logs`, so host ports don't matter; the gateway URL comes from
VOICECORE_GATEWAY (default http://127.0.0.1:8080). Order matters: the turn count runs before the orchestrator is killed.
"""
import json
import os
import subprocess
import sys
import time
import urllib.parse
from datetime import UTC, datetime
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
GATEWAY = os.environ.get("VOICECORE_GATEWAY", "http://127.0.0.1:8080")
pytestmark = pytest.mark.docker


def compose(*args, check=True) -> str:
    return subprocess.run(["docker", "compose", "--profile", "monitoring", *args], cwd=ROOT, check=check,
                          capture_output=True, text=True).stdout


def promql(q: str) -> list:
    url = "http://127.0.0.1:9090/api/v1/query?query=" + urllib.parse.quote(q, safe="")
    return json.loads(compose("exec", "-T", "prometheus", "wget", "-qO-", url))["data"]["result"]


def sink_lines(since: str) -> list[dict]:
    """Alerts the sink printed since `since` (RFC 3339), so lines from an earlier run never satisfy a wait."""
    out = []
    for line in compose("logs", "--no-log-prefix", "--since", since, "alert-sink").splitlines():
        try:
            out.append(json.loads(line))
        except ValueError:
            pass
    return out


def wait_for(what, check, deadline_s, every_s=5):
    end = time.time() + deadline_s
    while time.time() < end:
        if check():
            return
        time.sleep(every_s)
    pytest.fail(f"{what} did not happen within {deadline_s} s")


@pytest.mark.timeout(300)
def test_monitoring_counts_turns():
    before = sum(float(r["value"][1]) for r in promql("sum(voicecore_turns_total)"))
    for _ in range(3):
        subprocess.run([sys.executable, str(ROOT / "harness/smoke.py"), "--gateway", GATEWAY], check=True, timeout=60)
    wait_for("3 more turns in Prometheus",
             lambda: sum(float(r["value"][1]) for r in promql("sum(voicecore_turns_total)")) >= before + 3, 60)


@pytest.mark.timeout(600)
def test_alert_reaches_sink_then_resolves():
    start = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    last = lambda name: next((a["status"] for a in reversed(sink_lines(start)) if a["alertname"] == name), None)  # noqa: E731
    wait_for("a Watchdog heartbeat from this run", lambda: last("Watchdog") == "firing", 150)  # repeats every minute
    compose("kill", "agent-core")  # not a graceful stop: a draining process still serves metrics
    try:
        wait_for("OrchestratorDown firing", lambda: last("OrchestratorDown") == "firing", 240)
    finally:
        compose("up", "-d", "--wait", "agent-core")
    wait_for("OrchestratorDown resolved", lambda: last("OrchestratorDown") == "resolved", 240)
