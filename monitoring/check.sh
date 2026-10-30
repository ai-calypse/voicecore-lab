#!/usr/bin/env bash
# Seam 15: checks the monitoring config with the real tools, in their own images (CI job "monitoring", or locally).
set -euo pipefail
cd "$(dirname "$0")"
PROM=prom/prometheus:v3.5.0
AM=prom/alertmanager:v0.28.1
docker run --rm -v "$PWD/prometheus:/etc/prometheus:ro" --entrypoint promtool $PROM check config /etc/prometheus/prometheus.yml
docker run --rm -v "$PWD/prometheus:/p:ro" --entrypoint promtool $PROM test rules /p/tests/alerts_test.yml
docker run --rm -v "$PWD/alertmanager:/a:ro" --entrypoint amtool $AM check-config /a/alertmanager.yml
route() {  # route <expected receiver> <labels...>
  want=$1; shift
  docker run --rm -v "$PWD/alertmanager:/a:ro" --entrypoint amtool $AM config routes test --config.file=/a/alertmanager.yml --verify.receivers="$want" "$@" >/dev/null \
    || { echo "route $* did not reach $want"; exit 1; }
  echo "route $* -> $want"
}
route local-sink severity=critical alertname=OrchestratorDown
route local-sink severity=warning alertname=StageLatencyHigh
route watchdog-sink severity=none alertname=Watchdog
