# ADR 0003: Observability

**Status:** Logs accepted (S09-T04, 2026-10-30); metrics, alerts and the logs store proposed until S09-T05 ([plan](../PRODUCTION_PLAN.md)).

## Decision (to be confirmed with evidence)

- **Logs (accepted).** JSON lines when `LOG_FORMAT=json` (compose sets it), text otherwise. Python: an allow-list formatter (`voicecore/logs.py`) keeps `ts, level, logger, msg` plus `session_id, gen, kind, reason, provider, duration_ms`, and redacts loaded key values and key-shaped strings, in messages, fields and tracebacks (`exc`). JSON only for `LOG_FORMAT=json` exactly, in both services. An internal error logs `answer failed`, never `provider error`, so provider metrics stay clean. Protocol errors log only the exception type. The session id is passed explicitly at each call site rather than through a contextvar: there are four sites, and explicit is easier to follow. Go: `slog.NewJSONHandler`; the gateway logs no IPs, tokens or resume keys. `websockets` is quieted to WARNING, otherwise each health probe is a log line.
- Metrics: OpenTelemetry API in both services, Prometheus exporters (pull), computed from the trace stream so latency has one definition.
- Alerts: Prometheus rules tested with promtool; Alertmanager routes tested with amtool; a local alert sink.
- Logs store: Loki with compactor retention (7 days) via Alloy; no separate tracing backend (the JSONL traces stay the trace store).

## Evidence

- S09-T04: `tests/test_logs.py` (allow-list, redaction, provider error fields); `TestSessionEndLogLine` (Go, JSON handler; the resume key is absent).
- S09-T05: to be recorded.
