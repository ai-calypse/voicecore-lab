# Service targets

**Status:** Step 09 Phase 5, 2026-10-30. Every number on this page is a **target**, not a measurement. Measurements live in `reports/` and `EXECUTION_STATUS.md`, each labelled `live-provider`, `fake-provider` or `simulated`.

VoiceCore is a single-machine portfolio system, so these are targets for a demo deployment, not service level agreements. There is no 99.9% promise anywhere.

| Target | Threshold | Measured by | Alert |
|---|---|---|---|
| Server endpoint to first audio | p95 < 1,200 ms over 10 minutes | `voicecore_stage_ms{stage="endpoint_to_first_audio"}` (pairing rule: `voicecore/stages.py`) | [StageLatencyHigh](runbooks.md#stagelatencyhigh) |
| Provider error ratio | < 2% of calls per provider over 5 minutes | `voicecore_provider_errors_total` / `voicecore_provider_calls_total` | [ProviderErrorsHigh](runbooks.md#providererrorshigh) |
| Voice sessions ending in `error` | < 1% (mock CI run) | `voicecore_sessions_total{outcome="error"}` / all sessions | none; checked in CI |
| Spend | < 80% of each cap ($4.00 of $5.00) | `voicecore_spend_usd{pool="usd"}`, read from the ledger | [BudgetNearCap](runbooks.md#budgetnearcap) |
| Orchestrator event loop | p95 lag < 100 ms over 5 minutes | `voicecore_event_loop_lag_ms` (1 s sampler) | [EventLoopLagHigh](runbooks.md#eventlooplaghigh) |
| Both processes up | scrape succeeds | `up{job="agent-core"}`, `up{job="gateway"}` | [OrchestratorDown](runbooks.md#orchestratordown), [GatewayDown](runbooks.md#gatewaydown) |

**Why these numbers.**

- **1,200 ms.** The measured live server share is well under this (live p50 841 ms end to end, including the network and playout). A p95 over 1,200 ms on the server alone means something changed: a slower model route, a provider incident or a saturated loop.
- **2%.** One or two transient provider failures in a short demo are normal; the session retries 429s and asks the user to repeat on a stall. A sustained 2% means the provider or our key is in trouble.
- **80% of the cap.** It leaves room to finish the step's planned live checks, and time to stop before the hard cap refuses sessions.
- **100 ms.** Voice activity detection runs on the event loop. A loop that is late by 100 ms delays every session's mic frames, endpoint decision and audio.

**How to check one now:** open Grafana (`docker compose --profile monitoring up --wait`, then http://127.0.0.1:3001). Each target has a panel; the threshold line on it is the target.
