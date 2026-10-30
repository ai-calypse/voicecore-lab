# Step 09: Production Readiness

**Status:** In progress (started 2026-10-30). Phases 0–5 done; Phase 6 (resilience and circuit breakers) next.
**Estimated engineering effort:** about 110 hours.
**Task owner:** Implementation agent. The user decides on deploying, live spend beyond the approved checks, real Turnstile and paging credentials, and key rotation.

## Purpose and scope

Close the gaps a senior reviewer expects in a running system:

- health checks and graceful shutdown
- structured logs, metrics, dashboards and alerts with runbooks
- provider resilience: reconnects, circuit breakers, per-turn deadlines
- session security and abuse protection
- a capped public budget
- multi-copy scaling with shared state
- mock and live load evidence
- a deploy that is ready but not run

The work is test-first, at the seams listed in [the plan](./PRODUCTION_PLAN.md#b-new-test-seams-approving-this-plan-signs-off-seams-1420-seams-113-still-apply).

**Non-goals** (unchanged from [ADR 0001](./adr/0001-engine-ownership.md)):

- SaaS billing or tenants
- 99.99% SLO claims
- paid hosting
- deploying without the user's go-ahead

## Step-specific implementation-agent prompt

> Act as a senior real-time voice software engineer.
>
> Read [`docs/PRODUCTION_PLAN.md`](./PRODUCTION_PLAN.md) (plan v4, two independent reviews applied), this step, and the actual code. Implement the phases in order, one RED → GREEN → COMMIT slice at a time.
>
> Record evidence in this step's registers. Never spend money without the user's approval at the step that needs it. Never add attribution lines to commits.

## Required reading and prerequisites

- [Production plan v4](./PRODUCTION_PLAN.md): phases, slices, seams 14–20, skills, money.
- [Implementation plan §A](./IMPLEMENTATION_PLAN.md): the TDD rules, which still bind.
- [ADR 0001](./adr/0001-engine-ownership.md), [ADR 0002](./adr/0002-turn-policy.md).
- Steps 00–08 outputs, as recorded in [EXECUTION_STATUS.md](../EXECUTION_STATUS.md).

## Decision ownership

This step owns:

- the operational contracts: health, readiness, drain, log fields, metric names, alert rules, breaker rules, the resume key and token format, the multi-copy state split, and the deploy config;
- two new ADRs: [0003 observability](./adr/0003-observability.md) and [0004 deploy, abuse, resilience and scale](./adr/0004-deploy-abuse-resilience-scale.md).

A change to the wire protocol (`resume_key`, session id format) updates `packages/protocol/SPEC.md` and its golden vectors in the same slice.

## Phases and specific tasks

| Task | Plan phase | Outcome |
|---|---|---|
| S09-T00 | 0 | Setup and safety rails: ledger safety, isolated e2e ports, test helpers, data map, ADR stubs |
| S09-T01 | 1 | Bugs found by the surveys (keys parser, unsettled STT reservation, double `session.ended`) |
| S09-T02 | 2 | Health, readiness, graceful drain on both services, compose healthchecks |
| S09-T03 | 3 | Session security core: resume key, single-use IP-bound tokens, trusted proxies, copy-prefixed session ids |
| S09-T04 | 4 | Structured JSON logs with redaction |
| S09-T05 | 5 | Metrics from traces, Prometheus, Alertmanager, Loki, Grafana, targets, runbooks, incident process |
| S09-T06 | 6 | STT reconnect, circuit breakers, per-turn deadline, gateway dial retry and breaker, chaos scenarios |
| S09-T07 | 7 | Turnstile, CORS, prod config validation, CSP, CI security scanning |
| S09-T08 | 8 | Widget reconnect and Turnstile UI |
| S09-T09 | 9 | Public budget sub-pool, daily cap, per-IP quota, text-only extractive fallback |
| S09-T10 | 10 | Multi-copy (Redis, 2 gateways, 2 orchestrators, nginx), mock and live load, soak |
| S09-T11 | 11 | Fly deploy ready but not run, prod compose overlay, deploy workflow |
| S09-T12 | 12 | Privacy page, docs updates, final reviews |

## Risks, verification and recovery

- **Money.** Tests must never write the real ledger; that is fixed in S09-T00. E2E must never reach a live orchestrator: the isolated ports and no server reuse (S09-T00) cover it now, and the mock-only guard joins as globalSetup in S09-T02, once `/healthz` exists. Live checks need the user's approval at the step.
- **Docs corpus drift.** A fact changed in code must be updated in the docs pages in the same slice, or the assistant cites stale facts.
- **History rewrite (2026-10-30).** At the user's request, `Co-Authored-By` trailers were removed from every commit and the history was force-pushed. A local backup is in branch `backup/pre-attribution-rewrite` and a bundle. Commit ids cited in step docs were remapped.

## Acceptance checklist

- [ ] All phases' slices green; `make test`, `make e2e`, docs anchors, promtool and amtool tests, and all CI jobs pass
- [ ] The verification list in the plan has been run and recorded
- [ ] Spend ≤ $0.25 above the start of the step, checked in the ledger
- [ ] `code-review` (high), `health` and `document-release` run, with findings fixed

## Decisions and outputs register (fill in during implementation)

| Date | Task | Decision / output | Evidence |
|---|---|---|---|
| 2026-10-30 | S09-T00 | The ledger path is resolved per call. A root `conftest.py` gives every non-live test a temp ledger. Entries carry `ts` (`budget.now`). | `test_budget.py` (2 new); 129 passed; real ledger unchanged |
| 2026-10-30 | S09-T00 | memnet: `HTTPClientFrom` / `DialContextFrom`, ECONNREFUSED refusals, `Listener.RefuseNext(n)`. The refusal control lives in memnet, which owns connections; the plan had put it in fakeorch. fakeorch: `/readyz` with `SetReady`, and `Kill()`. | `memnet_test.go`, `fakeorch_test.go` |
| 2026-10-30 | S09-T00 | `MockSTT(error_after_ms)`; a `docker` pytest marker excluded from `make test` and CI; `--providers mock-billed` | `test_provider_contracts.py`, `test_server.py` |
| 2026-10-30 | S09-T00 | Demo e2e moved to ports 15173 / 18765 / 18080 / 18766 / 18081 / 18090; docs e2e to 13000. Servers never reused (code review: the first version reused them outside CI). `checkMockOnly` guard (5 s timeout, HTTP status checked), wired as globalSetup in S09-T02. | vitest 3/3; demo e2e 11/11 and docs e2e 2/2, run beside a live stack on the dev ports |
| 2026-10-30 | S09-T01 | `keys.key` ignores inline comments (after whitespace) and strips quotes; an empty value is unset. `budget.reserve_all`: all-or-nothing; earlier reservations are settled at 0 when a later one is refused (live and billed-mock paths). The gateway forwards an orchestrator's `session.ended` once and ends with its reason. | `test_keys.py`, `test_budget.py`, `test_server.py`, `TestBudgetRefusalReachesClientOnce` (was `[budget error]`) |
| 2026-10-30 | S09-T01 | Code review changes:<br>• `reserve_all` is atomic (one lock: all or nothing, nothing written on refusal or error).<br>• Keys parser: quotes first; `#` only after whitespace; an empty placeholder does not hide a later line.<br>• `live_providers` settles at 0 if building a provider throws.<br>• Gateway default reason `ended`, capped at 100 bytes.<br>Known edge, not fixed: an orchestrator ending a session while the client is inside its resume window; the client then resumes into nothing. | review on `b83b250`; 136 passed; Go race suite ok |
| 2026-10-30 | S09-T02 | **Orchestrator:**<br>• `AppState` plus `process_request` routes. `/healthz` returns `{status, providers, version}`. `/readyz` returns 200 only when loaded and not draining.<br>• WebSocket upgrades get 503 while starting or draining.<br>• Serving starts first; models load in a thread.<br>• SIGTERM/SIGINT: drain up to `--drain-s` (25 s), then `session.ended{shutdown}`, settles each budget, exit 0.<br>**Gateway:**<br>• `BeginDrain`/`Drain`: new tokens get 503, new sessions get 1013, resumes are still allowed.<br>• `/healthz`, `/readyz`; `Probe`/`-probe` (distroless healthcheck).<br>• main waits for drain and shutdown; version via ldflags.<br>**Compose:** healthchecks, `init: true`, `stop_grace_period: 35s`, restart policies, gateway `depends_on` agent-core healthy. CI uses `up --wait` and checks a graceful stop (exit 0).<br>**Runners:** the WSS runner and Playwright wait on orchestrator `/readyz`; the mock-only guard is now Playwright's globalSetup.<br>`python -m voicecore.budget orphans` (report only) lists today's 3 pre-`ts` orphans ($0.1785). | `test_server.py` (7, incl. a SIGTERM subprocess exiting 0 in < 5 s); `health_test.go` (5; drain test stable over 5 race runs); manual: gateway SIGTERM exits 0 in 0.02 s with no sessions |
| 2026-10-30 | S09-T03 | **Resume key:** `welcome.resume_key` (32 random bytes, hex). A resume needs `session_id` plus the key (`hmac.Equal`); a wrong or missing key is a new session. The SDK keeps the key in memory and sends it on reconnect.<br>**Tokens:** `exp.nonce.HMAC(exp.nonce.ip)`, single-use (used nonces in memory until expiry, swept at most once a second), bound to the client IP. A resume with the right key skips the token, so a spent token still reconnects. A hello refused with 1013/1011 gives its nonce back.<br>**Client IP:** peer address; `X-Forwarded-For` (all header lines) only from `-trusted-proxies`, rightmost untrusted hop, normalized (`ip:port`, brackets, IPv4-mapped); an unparsable hop falls back to the peer.<br>**Session ids:** `s-<copy id>-<16 hex>`, `-copy-id` (default `gw`, must match `^[a-z0-9]{1,32}$`).<br>Protocol: SPEC, vectors, Go/Python/TS codecs. Docs pages: realtime-gateway, wire-protocol, configuration, browser-sdk, live-providers, trace-events.<br>Code review changes: nonce given back on refusal; multi-line XFF; hop normalization (and before the trust check); sweep rate; copy-id check; dead import; SPEC fallback wording.<br>Known edges, not fixed here: (a) after the resume window the SDK reconnects with its spent token and gets 4001; it must fetch a new token, which is Phase 8's reconnect work. (b) A session resumed from a new IP stays counted under the IP that admitted it (each session passed the per-IP cap once; IP changes on resume are legitimate on mobile). | `security_test.go` (9: right/wrong key, single use, spent token + key, IP binding, XFF ×2, copy id, key never logged or traced, refused hello keeps its token); SDK `client.test.ts` resume sends the key |
| 2026-10-30 | S09-T04 | **Python:** `voicecore/logs.py` `Formatter`: JSON (`LOG_FORMAT=json`) or text, keeps `ts, level, logger, msg` plus `session_id, gen, kind, reason, provider, duration_ms`, and `exc` (traceback); redacts loaded key values, `sk-or-v1-…`, `sk_car_…` and long `token …` values. `provider error` at every `ProviderError` site (one helper); `answer failed` with traceback for internal errors; `session started/ended` (`duration_ms`), `session refused` (`reason: budget`), `protocol error` (type only). `websockets` quieted to WARNING.<br>**Go:** `LOG_FORMAT=json` selects `slog.NewJSONHandler`; `session started` and `session ended` (`session_id`, `reason`, `duration_ms`). Compose sets `LOG_FORMAT=json` for both.<br>Code review changes: the session setup (trace sink, engine, `Session`, `start`) moved inside the try, so a failure there still settles the budget reservations (was a money bug: they stayed `reserved`); tracebacks kept; JSON only on exact `json`; internal bugs not counted as provider errors; no client text in protocol-error lines; one formatter class. | `test_logs.py` (6), `test_session_setup_failure_still_settles_the_reservations`, `TestSessionEndLogLine`; manual JSON start/stop run |
| 2026-10-30 | S09-T05 | **One latency definition:** `voicecore/stages.py` pairs trace events by `turn_id` and generation (old traces without `turn_id` pair as before). `harness/timeline.py` uses it, and two recorded live runs reproduce their p50s (801.8 ms, 841.1 ms).<br>**New trace events:** `session/started`, `session/ended{reason}`, `turn/result{kind, result}`, `stt/connect`, `tts/request`; `turn_id` on `turn/endpoint`, `stt/turn_text`, `llm/request`.<br>**Orchestrator metrics** (`MetricsSink`, OpenTelemetry SDK 1.45.2, exporter 0.66b2, own registry): `voicecore_stage_ms`, `_turns_total`, `_sessions_total`, `_provider_calls_total`, `_provider_errors_total`, `_spend_usd`, `_event_loop_lag_ms`; `--metrics-port` (default off; compose 9464).<br>**Gateway:** `-admin-addr` with `/metrics` (`client_golang` 1.25.0, a registry per Server) and `/debug/counters`; new counters `tokens_issued`, `rejected_{ratelimit,host,upgrade,draining}`. go.mod now needs Go 1.26.<br>**Monitoring profile:** Prometheus 3.5.0, Alertmanager 0.28.1, alert sink, Loki 3.6.7 (7-day compactor retention), Alloy 1.10.0, Grafana 12.1.0 (`127.0.0.1:3001`). 8 rules, each with a runbook. Docs: `docs/ops/{slos,runbooks,monitoring,incidents}.md`, incident template, 2 write-ups.<br>Deviations from the plan: the gateway uses `client_golang` directly, not OpenTelemetry (ADR 0003). `voicecore_breaker_state` is not exported yet: Phase 6 adds it, and its rule and test exist now. `/debug/counters` stays on the public mux until Phase 7, so its 3 callers did not change. No Slack or email receiver, and no env switch for one: the config comment says where to add it. GatewayDown was added. | `test_metrics.py` (12), `test_session_and_turn_events`, `test_metrics_endpoint_type_lines`, `test_timeline.py` retry fixture, `admin_test.go` (2), `monitoring/check.sh` (threshold mutations caught), `test_monitoring.py` (docker, 2 passed in 136 s), Grafana screenshots in both themes |
| 2026-10-30 | S09-T05 | Code review changes:<br>• The ledger is read under a shared lock (`budget._entries`), so the spend gauge on the scrape thread never reads a half-written file.<br>• TTS errors are counted once per attempt, and a retry counts as a call; leftovers of an abandoned answer are traced as `tts/stale_error`.<br>• An internal bug is traced as `llm/internal_error`, never as a provider error.<br>• Hello refusals are counted (`rejected_token`, `_busy`, `_upstream`, `_draining`).<br>• The admin listener binds at start and exits 2 if it can't.<br>• One counters handler serves both listeners.<br>• The monitoring test reads only sink lines from its own run and URL-encodes queries.<br>• Port comments say what a prod overlay must do (`!reset` / `!override`).<br>Not changed: the per-generation sets in `Session` hold one int per generation, bounded by the 15-minute session cap. | `test_total_waits_for_a_writer…`, `test_tts_errors_never_outnumber_tts_calls`, `test_internal_bug_is_not_a_provider_error`, `TestHelloRefusalsAreCounted`; manual: admin port clash exits 2; docker monitoring rerun 2 passed in 203 s |
| 2026-10-30 | — | Commit attribution removed from all history (user request); project settings disable it from now on | `.claude/settings.json`; `git log --format=%B \| grep -ci co-authored` = 0 |

## Execution record

| Date | Phase | Commands and results |
|---|---|---|
| 2026-10-30 | 5 | `make test`: 165 passed (Python), Go race ok (gateway and experiments), TS 14 + 6 + 4. `make e2e`: demo 11, docs 2, anchors 342/0. `monitoring/check.sh`: promtool 8 rules, amtool routes ok. Monitoring profile on remapped host ports (the live demo held 8080/8765/3000): `test_monitoring.py` 2 passed in 136 s; the sink got OrchestratorDown `firing` then `resolved`. |
| 2026-10-30 | 4 | `make test`: 150 passed (Python), Go race ok, TS 14 + 6 + 4. `make e2e`: demo 11, docs 2, anchors 340/0. |
| 2026-10-30 | 3 | `make test`: 143 passed (Python), Go race ok, TS 14 + 6 + 4. `make e2e`: demo 11, docs 2, anchors 339/0. `harness/gate.py`: exit 0. `-copy-id eu/1` and `gw-1` exit 2. |
| 2026-10-30 | 2 | `make test`: 142 passed (Python), Go race ok, TS ok. `make e2e`: demo 11, docs 2, anchors 339/0. `harness/gate.py`: pass. |
| 2026-10-30 | 0 | `uv run pytest -m "not live and not docker"`: 131 passed. `go test -race ./...`: ok. `pnpm --filter @voicecore/demo test`: 3 passed. `pnpm --filter @voicecore/demo e2e`: 11 passed. `pnpm --filter @voicecore/docs e2e`: 2 passed. |

## Source and artifact change record

| Date | Paths | Why |
|---|---|---|
| 2026-10-30 | `conftest.py`, `voicecore/budget.py`, `harness/baseline_deepgram.py` | ledger safety |
| 2026-10-30 | `services/realtime-gateway/internal/{memnet,fakeorch}` | test helpers |
| 2026-10-30 | `voicecore/providers/mock.py`, `voicecore/server.py`, `pyproject.toml`, `Makefile`, `ci.yml` | mock drop, docker marker, billed mocks |
| 2026-10-30 | `voicecore/{stages,metrics,server}.py`, `runtime/session.py`, `harness/timeline.py`, `session/admin.go`, `cmd/gateway/main.go`, `monitoring/**`, `docker-compose.yml`, `Makefile`, `ci.yml` (job `monitoring`), `docs/ops/**`, ADR 0003, docs pages (trace events, configuration, wire protocol) | metrics, alerts, dashboards, runbooks, incidents (S09-T05) |
| 2026-10-30 | `voicecore/{logs,server}.py`, `voicecore/runtime/session.py`, `services/realtime-gateway/{session,cmd/gateway}`, `docker-compose.yml`, `reference/configuration.md`, `guides/troubleshooting.md`, ADR 0003, data map | structured logs (S09-T04) |
| 2026-10-30 | `services/realtime-gateway/{session,cmd/gateway}`, `packages/protocol/**`, `voicecore/protocol.py`, `packages/web-sdk/src/client.ts`, `apps/demo/e2e/capture.spec.ts`, docs pages above, `docs/ops/data-map.md` | session security core (S09-T03) |
| 2026-10-30 | `apps/demo/{playwright.config.ts,vitest.config.ts,e2e/*,public/embed-test.html,package.json}`, `apps/docs/playwright.config.ts` | e2e isolation |

## Handoff

Not yet. The step ends when the acceptance checklist is complete. The user then decides on deploying, the real Turnstile and paging credentials, and key rotation.
