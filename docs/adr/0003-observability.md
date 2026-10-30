# ADR 0003: Observability

**Status:** Proposed (stub, 2026-10-30). Filled in by Step 09 phases 4–5 ([plan](../PRODUCTION_PLAN.md)).

## Decision (to be confirmed with evidence)

- Logs: JSON lines with an allow-list of fields; loaded key values redacted.
- Metrics: OpenTelemetry API in both services, Prometheus exporters (pull), computed from the trace stream so latency has one definition.
- Alerts: Prometheus rules tested with promtool; Alertmanager routes tested with amtool; a local alert sink.
- Logs store: Loki with compactor retention (7 days) via Alloy; no separate tracing backend (the JSONL traces stay the trace store).

## Evidence

To be recorded by S09-T04 and S09-T05.
