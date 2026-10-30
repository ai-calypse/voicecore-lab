# ADR 0003: Observability

**Status:** Accepted (S09-T04 logs and S09-T05 metrics, alerts and logs store, 2026-10-30). [Plan](../PRODUCTION_PLAN.md).

## Decision

- **Logs (accepted).** JSON lines when `LOG_FORMAT=json` (compose sets it), text otherwise. Python: an allow-list formatter (`voicecore/logs.py`) keeps `ts, level, logger, msg` plus `session_id, gen, kind, reason, provider, duration_ms`, and redacts loaded key values and key-shaped strings, in messages, fields and tracebacks (`exc`). JSON only for `LOG_FORMAT=json` exactly, in both services. An internal error logs `answer failed`, never `provider error`, so provider metrics stay clean. Protocol errors log only the exception type. The session id is passed explicitly at each call site rather than through a contextvar: there are four sites, and explicit is easier to follow. Go: `slog.NewJSONHandler`; the gateway logs no IPs, tokens or resume keys. `websockets` is quieted to WARNING, otherwise each health probe is a log line.
- **Metrics (accepted).** Orchestrator: the OpenTelemetry SDK with a Prometheus reader on its own `CollectorRegistry`, fed by a `MetricsSink` that receives every session's trace events, so latency has one definition (`voicecore/stages.py`, also used by `harness/timeline.py`). Gateway: `client_golang` `CounterFunc`/`GaugeFunc` over the existing atomic counters, on a registry owned by each `Server`. OpenTelemetry would only have wrapped those same atomics, so it adds nothing there. Changed from the stub, which said OpenTelemetry in both.
- **Alerts (accepted).** Eight Prometheus rules tested with promtool (each fires on its target, stays quiet below it, and waits its `for`), Alertmanager routes tested with amtool, and a local alert sink. The Grafana alert-list panel could not read the external Alertmanager (HTTP 400), so the dashboard lists `ALERTS{alertstate="firing"}` from Prometheus instead.
- **Logs store (accepted).** Loki 3.6 with compactor retention of 7 days (`delete_request_store` is required once retention is on), fed by Alloy from the Docker socket. No tracing backend: the JSONL traces stay the trace store.

## Evidence

- S09-T04: `tests/test_logs.py` (allow-list, redaction, provider error fields); `TestSessionEndLogLine` (Go, JSON handler; the resume key is absent).
- S09-T05: `tests/test_metrics.py` (12), `test_metrics_endpoint_type_lines` (exported names), `TestAdminHandlerServesMetricsAndCounters`, `TestTwoServersDoNotCollide`, `monitoring/check.sh` (promtool and amtool; threshold mutations caught), `harness/tests/test_monitoring.py` (docker: turns counted, then OrchestratorDown fired and resolved; 2 passed in 136 s).
