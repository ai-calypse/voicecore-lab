# VoiceCore Lab — Step 09: production readiness (plan v4)

## Context

Steps 00–08 and the follow-ups are done:
- live voice turn p50 802–841 ms;
- a Docusaurus docs site with a conversational assistant;
- Deepgram for speech-to-text and text-to-speech;
- gpt-oss-120b on Cerebras.

The user asked which core software-engineering features are still missing. This plan builds them test-first, in small slices.
- Nothing is hosted and nothing is paid for, apart from one approved live load test.
- A Fly.io deploy is **prepared but not run**.

**History of this plan:**
- **v1** drafted.
- **Design review:** 5 verified problems, ordering fixes and YAGNI cuts.
- **v2.** The user then asked to *build* five things v2 had cut: circuit breakers, multi-copy scaling, Alertmanager, a live load test and an incident template.
- **Engineering review (`plan-eng-review`): "not ready", 18 findings.**
- **This v3** fixes all 18 and adds the five.
- **Second review** (`plan-eng-review` again): "ready with fixes". 13 of the 18 earlier findings were fully fixed and 5 only partly. It also found 15 new problems, mostly in the five added features.
- **This v4** applies all of them. Each fix is marked *(R2)*.

**What the code does today** (read-only surveys, 2026-10-30):

- **Observability**
  - JSONL traces, only with `--trace-dir`.
  - Gateway `/debug/counters` with no auth. It is used by `rig_test.go:76`, `tracer.spec.ts:22` and `wss.py:25`.
  - Plain-text logs. No metrics.
  - No trace events for session start or end, or for a turn's result.
  - `turn/endpoint` has no generation id.
  - The stage pairing rule lives only in `harness/timeline.py:49-53`.
- **Lifecycle**
  - No health endpoints.
  - `main()` loads the VAD and the docs index *before* `serve()` starts (`server.py:163-177`).
  - Python is PID 1 in Docker with no signal handler, so `docker stop` SIGKILLs it after 10 s.
  - The gateway ends all sessions at once on SIGTERM and keeps accepting new ones meanwhile.
  - The gateway image is distroless (no curl).
- **Resilience**
  - STT never reconnects.
  - The gateway dials the orchestrator once (then 1011).
  - No breakers. No per-turn deadline.
  - Cartesia has 15,531 of 16,000 credits used, so a Cartesia fallback (1,500 per session) cannot run.
- **Budget** (`budget.py`)
  - The ledger path is bound when the module is imported (`budget.py:17,61`), so tests can write the real `benchmarks/spend_ledger.json`.
  - Entries have no timestamp.
  - If the LLM reservation fails, the STT reservation is left unsettled (`server.py:86-87`).
  - `factory.py` only allows pool `usd`.
- **Security**
  - Anyone with a `session_id` can resume that session.
  - Tokens are reusable for 60 s, and `client.ts:42` re-sends the same token on resume.
  - `Access-Control-Allow-Origin: *`.
  - The client IP comes only from `RemoteAddr`. In Go tests memnet's `RemoteAddr` is always `"pipe"` (`memnet.go:36`).
  - The gateway secret is random if unset.
  - No CI scanning; actions are pinned by tag.
  - `keys.py` treats inline comments as the key.
  - A budget refusal reaches the client as two `session.ended` events.
- **Tests and ports**
  - Demo Playwright uses :8765/:8080/:8766/:8081/:5173 with `reuseExistingServer: true`. A local live stack or the compose demo on those ports would be reused, and that spends money.

**User decisions:**
- Build all areas, including circuit breakers, multi-copy scaling (Redis-shared state, two copies behind a load balancer), Alertmanager, a live load test (about $0.16) and an incident template.
- No paid hosting. A new Fly app `voicecore` is fully configured and deployed only on the user's "go". `speakos-api` is untouched.
- Self-hosted monitoring in compose: OpenTelemetry, Prometheus, Alertmanager, Loki and Grafana.
- A capped "public" budget pool.
- Turnstile with test keys.

**Done means:**
- `docker compose --profile monitoring up --wait` shows dashboards, and a stopped orchestrator pages the local alert sink.
- `docker compose --profile scale up` runs 2 gateways and 2 orchestrators that share Redis and survive a copy dying.
- Stopping a container lets its calls finish.
- A dropped STT connection reconnects. A failing provider trips its breaker.
- CI scans dependencies and secrets.
- `reports/load.md` has mock and live load numbers.
- `docs/ops/` has runbooks and incident write-ups.
- `deploy/fly/` is one command away from a deploy.

**Words used in this plan:**

| Word | Meaning |
|---|---|
| liveness `/healthz` | "the process is alive" |
| readiness `/readyz` | "send me new users" |
| drain | finish current calls, take no new ones |
| circuit breaker | after repeated failures, stop calling a provider for a while and fail fast |
| copy | one running gateway or orchestrator process |
| alert rule | a query that fires when a target is missed |
| runbook | what to do when an alert fires |
| incident write-up | what happened, why, and what changed |

---

## A. How each slice is done (same TDD loop)

One table row is one **slice**.

1. **RED.** Write only the named test. Run it. It must fail on its assertion. If a test needs a missing helper or mock fault, that helper is its own earlier slice.
2. **GREEN.** Write the least code that passes. Run the whole suite for that language.
3. **COMMIT.** Use `test(…)`, `feat(…)` or `fix(…)`. Run the secret scan: the grep for now, gitleaks after Phase 7. Push at least once per phase.

Rules (`docs/IMPLEMENTATION_PLAN.md` §A):
- Literal expected values.
- Mock only edges: provider APIs, Cloudflare siteverify, network, clocks.
- **Clocks:** the monotonic clock is injected (looptime / `synctest`). The wall clock, used only for ledger timestamps and daily caps, is a second clock injected at the edge as `budget.now`.
- Every number is labelled `fake-provider`, `live-provider`, `simulated`, `manual` or `target`.

**End of every phase:**
- `make test`, `make e2e`, the docs build plus `check_docs_anchors.py`, and the promtool/amtool tests (once they exist).
- The `code-review` skill (medium); fix what it finds.
- Step-09 registers, an `EXECUTION_STATUS.md` row, commit and push.

## B. New test seams (approving this plan signs off seams 14–20; seams 1–13 still apply)

| # | Seam | Tool and existing helper | Catches |
|---|---|---|---|
| 14 | Orchestrator lifecycle | in-process: `websockets.serve` on `127.0.0.1:0` with an injected providers factory. Plus **one** subprocess test: real `python -m voicecore.server` with a 2-page `--docs-dir`, sending SIGTERM | health, readiness, drain, settle, exit code |
| 15 | Monitoring and deploy config | `promtool test rules`, `promtool check config`, `amtool check-config`, `amtool config routes test`, `docker compose config --quiet`, `flyctl config validate` (Docker or CI) | rules and routes that never or always fire; broken config |
| 16 | Metrics from traces | `MetricsSink` fed literal trace events, OpenTelemetry `InMemoryMetricReader`, injected `MeterProvider` | names, labels, values |
| 17 | Log records | Python stream handler with the JSON formatter; Go `slog.NewJSONHandler(&buf)` in the rig | missing ids; leaked text or keys |
| 18 | Shared-state store contract | Python tests parametrised over `FileStore` and `RedisStore`; Go tests over `memStore` and `redisStore`. Real `redis:7` (CI service container, `make redis` locally); skipped without Redis | atomic reserve, daily caps, nonces, quotas |
| 19 | Gateway package units | plain Go tests in `session/` for logic moved out of `main.go`: `Config.ValidateProd()`, `Probe(url)`, `AdminHandler()` | prod config, probe exit codes, admin routes |
| 20 | E2E safety | unit tests (vitest) for `checkMockOnly(url)` used by Playwright `globalSetup` | e2e running against live providers |

Seams reused:
- seam 2: `session/rig_test.go::run`, memnet (extended in Phase 0), fakeorch;
- seam 4: `tests/runtime_helpers.py::make`, looptime, `providers/mock.py`;
- seam 9a: `harness/runner/chaos.py`;
- seam 9b: `harness/runner/wss.py`;
- seam 10: `tests/test_budget.py`;
- seam 13: Playwright.

## C. Skills

| When | Skill |
|---|---|
| Every slice | `tdd` |
| Phase 0 threat model and data map; Phase 7 end | `cso` |
| First use of a library or config. Done **at the start of the phase that uses it**; versions and dates go in the register. OpenTelemetry Python and Go, `opentelemetry-exporter-prometheus` (pre-1.0, global registry), websockets 17 `process_request`, Grafana provisioning, Loki retention (compactor), Alloy Docker logs, Alertmanager and `amtool`, Turnstile siteverify, redis-py `register_script`, go-redis, nginx `hash … consistent` with WebSocket upgrade, `fly.toml` (`[mounts]`, `kill_signal`, `kill_timeout`, `[[metrics]]`, `[http_service]`, checks, `fly-replay`) | Context7 |
| Signals, compose stop, CI pinning, ledger and money code, live load | `careful` |
| Grafana dashboard | `dataviz` |
| Widget states (reconnecting, Turnstile, budget notice, privacy link) | `ui-taste`, `browse` screenshots, `qa` with mocks |
| Live failures or flaky tests | `investigate` |
| End of Phase 7, and before the deploy is offered | `security-review` |
| Load, soak, live load | `benchmark` |
| Canary run against local compose | `canary` |
| Each phase end | `code-review` (medium). Final: `code-review` (high), `health`, `document-release` |

## D. Money

| Item | Cost |
|---|---|
| All tests, mock load and soak | $0 |
| **Live load test** (Phase 10): Aura speaks 12 VoiceCore questions (local-only clips) about $0.01, plus 5 parallel live sessions × 2 rounds about $0.15. Confirm the amount at the step. | ~$0.16 |
| Optional: provider contracts after STT reconnect (about $0.05), assistant eval re-run (about $0.02). Ask at the step. | ~$0.07 |
| **Ceiling** | **$0.25** |

- No Cartesia use. Its fallback is cut: 469 credits are left, fewer than one session needs.
- **Fly** costs $0 until a deploy is approved. Once deployed, a ledger volume costs a few cents a month even when stopped. This is stated in the deploy guide.

## E. Where new docs go

`apps/docs/docs/**` is the assistant's corpus. A new page there changes retrieval and the eval, the CI vector cache key, and the agent-core image. So:
- **Ops pages** (data map, targets, runbooks, incidents, deploy, key rotation) go in `docs/ops/`.
- **Privacy** goes in `apps/docs/src/pages/privacy.md`, which is not ingested.
- **Existing pages whose facts change are updated in the same slice** *(R2)*. Every slice that changes a documented fact greps `apps/docs/docs` and `packages/protocol/SPEC.md` for the old fact and updates the hits. Known hits: `/debug/counters` (`architecture/realtime-gateway.md:85,102`, `reference/wire-protocol.md:174` and others), the token format (`realtime-gateway.md:20`), close codes, flags (`reference/configuration.md`) and widget attributes (`getting-started/embed-the-widget.md`). Run the anchor check afterwards. The assistant must never cite a stale fact.

---

## Phase 0 — Setup and safety rails (~6 h)

| # | Do / RED test (literal) | GREEN / check |
|---|---|---|
| 0.1 | Write `docs/step_09_production_readiness.md` in step-doc format: tasks S09-T01…T12, acceptance, registers. Link it from `MASTER_AGENT_GUIDE.md` §4 and `docs/IMPLEMENTATION_PLAN.md`. Save this plan as `docs/PRODUCTION_PLAN.md`. Add an `EXECUTION_STATUS.md` row. | links resolve |
| 0.2 | Threat model and data map with `cso`. Output `docs/ops/data-map.md`: per process, what it stores, logs and sends. This decides the log allow-list (Phase 4). | reviewed |
| 0.3 | **Ledger safety.** `test_ledger_path_is_resolved_at_call_time`: set `VOICECORE_LEDGER` to a tmp path *after* import, `reserve()` → the entry lands in the tmp file, not `benchmarks/spend_ledger.json`. | `budget.py` reads the env var inside each call. A root `conftest.py` autouse fixture points `VOICECORE_LEDGER` at `tmp_path` for every test not marked `live`. |
| 0.4 | `test_reserve_writes_wall_clock_ts`: `budget.now = lambda: 1_761_800_000.0` → the entry has `"ts": 1761800000.0` | `reserve()` adds `ts`. Old entries without `ts` stay readable. |
| 0.5 | **E2E ports and live guard.** vitest `checkMockOnly`: `{"providers":"live"}` → throws `refusing to run e2e against live providers`; `{"providers":"mock"}` → ok; connection refused → throws `no orchestrator at …` | `apps/demo/e2e/check-mock-only.ts`, used by Playwright `globalSetup` (switched on in Phase 2, once `/healthz` exists). Move the demo e2e stack to ports 18765 / 18080 / 18766 / 18081 / 15173 and update the hard-coded ports in `tracer.spec.ts`, `voice.spec.ts`, `public/embed-test.html` and `src/main.ts` (env `VITE_GATEWAY`). Set `reuseExistingServer: !process.env.CI`. |
| 0.6 | **memnet client addresses.** Go `TestMemnetRemoteAddrIsTheDialerAddress`: `n.DialFrom("198.51.100.7:5000")` → the server sees `r.RemoteAddr == "198.51.100.7:5000"` | `internal/memnet`: a per-dial source address; the default stays `"pipe"` |
| 0.7 | **Mock fault.** `test_mock_stt_error_after_ms_raises_retryable_once`: `MockSTT(error_after_ms=1000)`, 1,000 ms of audio sent → `events()` raises `ProviderError("retryable")` | `providers/mock.py` |
| 0.8 | ADR stubs: `0003-observability.md`, `0004-deploy-abuse-resilience-scale.md` | exist |
| 0.9 | **fakeorch helpers** *(R2)*: Go `TestFakeorchReadyzKillRefuse` checks three helpers. `o.SetReady(503)` makes `GET /readyz` return 503. `o.Kill()` closes every live connection. `o.RefuseDials(2)` refuses the next 2 dials. | `internal/fakeorch` |
| 0.10 | **memnet refusal** *(R2)*: Go `TestMemnetRefusalIsConnRefused`. A dial to a closed listener returns an error where `errors.Is(err, syscall.ECONNREFUSED)` is true. | `internal/memnet` wraps the refusal in `&net.OpError{Err: syscall.ECONNREFUSED}` |
| 0.11 | **Docker test marker** *(R2)*: register a `docker` pytest marker in `pyproject.toml`. `make test` and the CI python job run `-m "not live and not docker"`. Docker tests carry `@pytest.mark.timeout(300)`, because the global timeout is 60 s. | `pytest --markers` lists `docker`, and `make test` collects 0 docker tests |
| 0.12 | **Demo unit tests** *(R2)*: `apps/demo/vitest.config.ts` includes only `e2e/*.test.ts` and `src/**/*.test.ts`, never the Playwright `*.spec.ts` files. This is used by 0.5. | `pnpm --filter @voicecore/demo exec vitest run` runs only 0.5's test |
| 0.13 | **Billed mocks** *(R2)*: `test_mock_billed_settles_literal_amounts`. With `--providers mock-billed`, each session reserves and settles STT $0.001, LLM $0.0005 and TTS $0.0002, so the ledger maths can be checked without spending. | `server.py` mode `mock-billed` (mock providers plus real ledger calls) |

## Phase 1 — Bugs found by the surveys (~2 h)

| # | RED test (literal) | GREEN |
|---|---|---|
| 1 | `test_key_ignores_inline_comment_and_quotes`: `DEEPGRAM_API_KEY=   # stt` → `None`; `X="abc"  # c` → `"abc"` | `keys.py` |
| 2 | `test_llm_reservation_refused_settles_the_stt_reservation_at_0`: ledger at **$4.95**; the STT reservation ($0.0385) fits, the LLM one ($0.02) does not → the client gets `session.ended{budget}`; the STT entry is `settled`, amount 0 | `live_providers()` settles earlier reservations when a later one fails (injected providers factory, tmp ledger) |
| 3 | Go `TestBudgetRefusalReachesClientOnce`: fakeorch sends `session.ended{budget}` and closes → the client gets one `session.ended`, reason `"budget"` | `end()` doesn't repeat an upstream `session.ended` |

## Phase 2 — Health checks and graceful shutdown (~8 h, seams 2, 14, 19; skill `careful`)

| # | RED test (literal) | GREEN |
|---|---|---|
| 1 | Py `test_healthz_ok`: `GET /healthz` → 200 `{"status":"ok","providers":"mock","version":"dev"}` | `serve(..., process_request=…)` (check with Context7); version from `VOICECORE_VERSION` |
| 2 | Py `test_readyz_503_while_loading_then_200`: the injected loader blocks on an event → 503 `{"ready":false}`; release it → 200 | `main()` **starts serving first**, then loads the VAD and the index in `asyncio.to_thread`, then sets `ready`. While starting, `process_request` answers a WebSocket upgrade with **HTTP 503** *(R2)*. It is not accepted and then closed: an accepted socket would let the gateway send `welcome` first. |
| 3 | Py `test_drain_refuses_new_keeps_open`: `state.drain()` → `/readyz` 503 `{"draining":true}`; a new WebSocket upgrade gets **HTTP 503** *(R2)*; the open session still answers | `process_request` checks the state |
| 3b | Go `TestUpstreamHandshake503ClosesBeforeWelcome` *(R2)*: fakeorch `SetReady(503)` answers the upgrade with 503 → the client gets close 1013 `"unavailable"` and **no** `welcome`. With a second upstream configured (Phase 10), the session goes there instead. Nothing is reserved before the handshake. | gateway dial path |
| 4 | Py `test_shutdown_ends_open_sessions_and_settles_each_once` (in-process): providers factory with counting settle callables, `drain_s=0.5`, `await state.shutdown()` → the client gets `session.ended{reason:"shutdown"}`; each settle is called once | `AppState.shutdown()` |
| 5 | Py `test_sigterm_exits_0_within_5s` (one subprocess test, 2-page `--docs-dir`, `--drain-s 1`) | `loop.add_signal_handler(SIGTERM/SIGINT, …)` → `shutdown()` → exit 0 |
| 6 | Go `TestPostSessionWhileDrainingIs503`; `TestHelloDuringDrainClosesWith1013` | `Server.Drain()` flag checked in the token handler and in `newSession` (fixes the race where new sessions slipped in during shutdown) |
| 7 | Go `TestDrainEndsSessionsWithShutdownAfterTimeout` (synctest, 25 s) → sessions 0, reason `"shutdown"` | `main.go`: signal → `gw.Drain(25s)` → `srv.Shutdown(ctx)`; `main` waits on a done channel |
| 8 | Go `TestHealthzAndReadyz`: `/healthz` 200 `{"status":"ok","version":"dev"}`; `/readyz` 200, then 503 after `Drain()` (and 503 while every upstream breaker is open, from Phase 6) | handlers in `session` |
| 9 | Go (seam 19) `TestProbeExitCodes`: `Probe(url)` → 0 on 200, 1 on 503 or connection refused | `session.Probe`; `main.go -probe URL` calls it (distroless image, no curl) |
| 10 | **Compose**:<br>• healthchecks: gateway `-probe`, agent-core a `python -c` urllib probe of `/readyz`, nginx `wget`, each with `start_period: 60s`;<br>• `init: true`, `stop_grace_period: 35s`, `restart: unless-stopped`;<br>• gateway `depends_on: {agent-core: {condition: service_healthy}}`;<br>• switch the Playwright `globalSetup` mock-only check on. | CI compose job uses `docker compose up --wait` and `/healthz`. |
| 11 | `test_orphans_reports_reserved_older_than_1h_or_without_ts`: entries at t-2h, at t-10m, and one with no `ts` → 2 reported | `python -m voicecore.budget orphans` (report only; orphans over-count, the safe side). Today's 3 real orphans ($0.1785) get listed. |

Proof to record: `docker compose kill -s SIGTERM agent-core` during a mock session → that session gets `shutdown`, nothing is left `reserved`, and the container exits within 30 s.

## Phase 3 — Session security core (~6 h, seam 2)

This comes before logging, so logs can safely contain session ids.

| # | RED test (literal) | GREEN |
|---|---|---|
| 1 | Go `TestResumeWithWrongKeyStartsNewSession` → `resumed:false`, new id; `TestResumeWithRightKeyResumes` → `resumed:true` | `welcome.resume_key` (32 random bytes, hex), checked with `hmac.Equal`. Update `SPEC.md` and `packages/protocol/vectors/events.json`; the TS, Go and Python golden tests change with it. |
| 2 | Go `TestTokenIsSingleUse`: a 2nd new-session hello with the same token → 4001 | token = `exp.nonce.HMAC(exp, nonce, ip)`; used nonces kept until expiry (`memStore`; Redis in Phase 10) |
| 3 | Go `TestSpentTokenPlusRightResumeKeyResumes`: the token was already used by the original hello, and a resume within 10 s with the right `resume_key` → `resumed:true`. A spent token with no key → 4001. | the token check is skipped when the hello carries a valid `resume_key` for a detached session. **Fixes the reconnect break.** |
| 4 | Go `TestTokenBoundToClientIP` (memnet `DialFrom`): minted from 198.51.100.7, used from 203.0.113.5 → 4001 | the IP is inside the HMAC |
| 5 | Go `TestXFFOnlyFromTrustedProxy`: from 203.0.113.5 with `X-Forwarded-For: 1.2.3.4` → IP `203.0.113.5`; from a trusted CIDR → `1.2.3.4` | `-trusted-proxies` flag and a `clientIP()` helper |
| 6 | Go `TestResumeKeyNeverLoggedOrTraced` (log buffer + trace buffer) | — |
| 7 | Go `TestSessionIDCarriesCopyID` *(R2)*: `-copy-id gw1` → welcome `session_id` matches `^s-gw1-[0-9a-f]{16}$` | `-copy-id` flag (default `gw`). Phase 10's load balancer routes resumes by this prefix. Update `SPEC.md` and the docs pages that show the session id format. |

## Phase 4 — Structured logs (~4 h, seam 17)

| # | RED test (literal) | GREEN |
|---|---|---|
| 1 | `test_json_log_line_keeps_only_allowed_fields`: `extra={"session_id":"s-1","text":"q"}` → keys exactly `{"ts","level","logger","msg","session_id"}` | `voicecore/logs.py`: allow-list JSON formatter (`session_id`, `gen`, `kind`, `reason`, `provider`, `duration_ms`); session id from `contextvars` |
| 2 | `test_known_key_values_are_redacted`: env `DEEPGRAM_API_KEY=dg-test-123`, msg `"failed dg-test-123"` → `"failed [redacted]"` | redact loaded key values and the `sk-or-v1-`, `sk_car_` and `Token \S+` patterns |
| 3 | `test_provider_error_logged_with_kind_and_provider`: MockLLM 429 → `{"msg":"provider error","provider":"llm","kind":"rate_limited"}` | log at the `ProviderError` sites in `session.py` |
| 4 | Go `TestSessionEndLogLine`: rig + JSON handler → `{"msg":"session ended","reason":"client","session_id":…}`; the `resume_key` is absent | `main.go` JSON handler; `slog.With("session_id", …)` in `session` |

`LOG_FORMAT=text` keeps logs human-readable locally.

## Phase 5 — Metrics, dashboards, alerts, runbooks, incidents (~16 h, seams 15, 16, 4; skill `dataviz`)

**One definition of latency.** Metrics are computed from trace events. The pairing rule moves from `harness/timeline.py` into `voicecore/stages.py`, and both the metrics and `timeline.py` call it.

| # | RED test (literal) | GREEN |
|---|---|---|
| 0a | `test_session_and_turn_events`: a mock text turn emits `session/started`, `turn/result{kind:"text",result:"answer"}`, then `session/ended{reason:"client"}` on close | new trace events in `session.py` and `server.py` |
| 0b | `test_stages_pairs_endpoint_request_first_token_first_audio` (literal µs as in row 1) and `harness/tests/test_timeline.py` still passing on its fixtures | `voicecore/stages.py`; `timeline.turn_breakdown` calls it |
| 1 | `test_stage_histogram_from_trace_events`: `turn/endpoint` 1,000,000 µs, `llm/request` 1,002,000, `llm/first_token` 1,262,000, `tts/first_audio` 1,412,000 (gen 1) → `endpoint_to_first_audio` count 1, sum 412.0; `llm_first_token` sum 260.0 | `voicecore/metrics.py: MetricsSink(meter)`. `Tracer` takes a list of sinks; the metrics sink is always on, the JSONL sink is optional. |
| 1b | Edge cases (same test file):<br>• a typed turn (no endpoint) records only `llm_first_token` and `tts_first_audio`;<br>• a second LLM attempt measures from the last `llm/request`;<br>• a cancelled generation records nothing after the cancel;<br>• `session/ended` drops per-session state (an internal dict is empty) | same |
| 2 | `test_provider_errors_counted_by_kind`: 3 × `llm/error kind=rate_limited` → counter 3 | same |
| 2b | `test_provider_calls_counted` *(R2)*: 4 × `llm/request` and 1 × `llm/error` → `voicecore_provider_calls_total{provider="llm"}` = 4. This is the denominator for the "> 2%" error-ratio alert. Also add `stt/connect` and `tts/request` trace events. | `MetricsSink`; new trace events |
| 2c | `test_sessions_total_by_outcome` *(R2)*: `session/ended{reason:"budget"}` → `voicecore_sessions_total{outcome="budget"}` = 1 | `MetricsSink` |
| 2d | `test_loop_lag_from_timestamps` *(R2)*: pure function, expected tick at 10.000 s, actual 10.180 s → lag 180 ms; a negative value is clamped to 0 | `voicecore/metrics.py: loop_lag_ms()`, plus a 1 s sampler task started in `main()` (thin, not unit-tested) |
| 2e | `test_typed_turn_after_voice_turn_has_no_endpoint_stage` *(R2)*: voice turn t1 then typed turn t2 → t2 records no `endpoint_to_request`. `stages.py` pairs by `turn_id`, not `last_before`. Also `test_first_token_measured_from_the_attempt_that_produced_it`: requests at 1.00 s and 3.00 s (retry), first token at 3.25 s → `llm_first_token` 250 ms. `harness/timeline.py` switches to the same rule, and `harness/tests/test_timeline.py` gets a retry fixture. | `voicecore/stages.py` |
| 3 | `test_spend_gauge_reads_ledger`: tmp ledger with $1.25 settled → `voicecore_spend_usd{pool="usd"}` = 1.25 | observable gauge |
| 4 | Subprocess server test (seam 14) `test_metrics_endpoint_type_lines`: `GET :<port>/metrics` contains these exact lines:<br>• `# TYPE voicecore_turns_total counter`<br>• `# TYPE voicecore_stage_ms histogram`<br>• `# TYPE voicecore_spend_usd gauge`<br>• `# TYPE voicecore_breaker_state gauge`<br>Exporter suffixes are pinned here, and the same names are the promtool input series in row 7. | OpenTelemetry Prometheus reader on `--metrics-port 9464`, bound to `0.0.0.0` but never published in compose. Its global registry stays inside the subprocess, so it never leaks between tests. |
| 5 | Go (seam 19) `TestAdminHandlerServesMetricsAndCounters`: `gw.AdminHandler()` serves `/metrics` with `# TYPE gateway_drops_total counter`, and also `/debug/counters`. Then update the 3 callers: `rig_test.go` `counters()` uses a second memnet listener; `tracer.spec.ts`; `wss.py`. | `session.AdminHandler()` with the OpenTelemetry Go Prometheus exporter, using **one Prometheus registry per `Server`** *(R2)* (never the default registry), so `TestTwoRigsDoNotCollide` passes. `Snapshot()` gains `tokens_issued` and `rejected_{ratelimit,host,origin,draining}` (the `session` package changes, deliberately). `main.go -admin-addr :9091`. The dev compose publishes it on `127.0.0.1:9091`, and agent-core's metrics on `127.0.0.1:9464`, so the host-side harness can read them *(R2)*. The prod overlay and Fly never publish them. `/debug/counters` leaves the public mux in Phase 7. |
| 6 | **Targets** in `docs/ops/slos.md`, all labelled `target`:<br>• server endpoint→first audio p95 < 1,200 ms;<br>• provider error ratio < 2%;<br>• voice sessions ending in `error` < 1% (mock CI);<br>• spend < 80% of each cap. | — |
| 7 | **Rule tests before the rules.** `monitoring/prometheus/tests/alerts_test.yml` (promtool, `evaluation_interval: 15s`):<br>• `BudgetNearCap`: fires at `voicecore_spend_usd{pool="usd"}` = 4.10 for 5 m, not at 3.90;<br>• `StageLatencyHigh`: histogram p95 > 1,200 for 10 m;<br>• `ProviderErrorsHigh`: > 2% for 5 m;<br>• `OrchestratorDown`: `up{job="agent-core"} == 0` for 1 m;<br>• `EventLoopLagHigh`: p95 > 100 ms for 5 m;<br>• `BreakerOpen`: state == 2 for 1 m (Phase 6 feeds it);<br>• `Watchdog`: always firing.<br>Each rule has `severity` and a `runbook_url` pointing at `docs/ops/runbooks.md#<alert>`. | `monitoring/prometheus/alerts.yml` |
| 8 | **Routing tests before the routes** (`amtool config routes test`):<br>• `severity=critical alertname=OrchestratorDown` → `local-sink`;<br>• `severity=warning` → `local-sink`;<br>• `alertname=Watchdog` → `watchdog-sink`;<br>• inhibition: while `OrchestratorDown` fires, `StageLatencyHigh` and `ProviderErrorsHigh` are muted (`amtool alert query` in the CI job). | `monitoring/alertmanager/alertmanager.yml`: `group_by [alertname]`, `group_wait 30s`, **`group_interval 30s`** *(R2: the 5-minute default delays "resolved")*, `repeat_interval 4h`. Receivers: `local-sink` and `watchdog-sink` are webhooks to `alert-sink`, a 30-line Python container that prints one JSON line per alert. Slack and email receivers are switched on by env and off by default; no credentials in the repo. |
| 9 | Compose profile `monitoring`:<br>• `prometheus` (scrape 5 s, eval 15 s, targets agent-core:9464 and gateway:9091; alerting → Alertmanager);<br>• `alertmanager`;<br>• `alert-sink`;<br>• `loki` with the compactor `retention_enabled: true` and `retention_period: 168h` (without the compactor nothing is deleted);<br>• `alloy` (Docker logs → Loki);<br>• `grafana` (provisioned datasources and dashboards, anonymous viewer, `127.0.0.1:3001`).<br>Images pinned (digests in Phase 11). | CI job `monitoring`: `compose --profile monitoring config --quiet`, `promtool check config`, `promtool test rules`, `amtool check-config`, route tests |
| 10 | `test_alert_reaches_sink` (marked `docker`, CI job `monitoring`): bring up the profile with mocks, then **`docker compose kill agent-core`** *(R2: a graceful stop keeps metrics up during the drain)*. Poll the `alert-sink` logs every 5 s for up to **240 s** for `"alertname":"OrchestratorDown","status":"firing"`. Start agent-core again; `"resolved"` arrives within 240 s. | — |
| 11 | `test_monitoring_counts_turns` (docker, CI): `harness/smoke.py` × 3, then poll Prometheus every 5 s up to 60 s until `sum(voicecore_turns_total)` = 3 | — |
| 12 | Dashboard `monitoring/grafana/dashboards/voicecore.json` with these rows:<br>• stage latency p50/p95 (`dataviz` palette);<br>• sessions and outcomes;<br>• provider errors, reconnects and breaker state;<br>• spend vs cap;<br>• gateway drops and rejections;<br>• firing alerts;<br>• Loki logs filtered by a `session_id` variable. | `browse` screenshots in both themes go into `docs/ops/monitoring.md` |
| 13 | `docs/ops/runbooks.md`: one section per alert, covering meaning, the first panel and query to check, the fix, and how to verify | anchors match each `runbook_url` |
| 14 | **Incidents.** `docs/ops/incidents/TEMPLATE.md` sections:<br>• summary;<br>• impact;<br>• detection;<br>• UTC timeline;<br>• root cause;<br>• what went well and badly;<br>• action items with owner and link;<br>• blameless note.<br>`docs/ops/incidents.md`: SEV1 voice down for all, SEV2 degraded, SEV3 cosmetic; roles; write-ups required for SEV1 and SEV2. | template |
| 15 | Two real write-ups, each action item linking a commit:<br>• `2026-10-30-tts-session-cap.md`: speech stopped after about 6 answers when Cartesia's 1,500-character cap ran out silently.<br>• `2026-10-30-benchmark-hit-wrong-stack.md`: a leftover docker stack on :8080 answered the benchmark. | facts from the git log and `EXECUTION_STATUS.md` |

## Phase 6 — Resilience and circuit breakers (~12 h, seams 4, 9a, 2, 15)

| # | RED test (literal) | GREEN |
|---|---|---|
| 1 | `test_stt_drop_reconnects_once_keeps_cap`: `MockSTT(error_after_ms=1000)`, and the factory's 2nd stream returns the final → answer delivered; trace `stt/reconnect` (gen none) emitted once; the audio-seconds counter continues | `Session(stt_factory=)`. Streams share one reservation and audio counter (the same pattern as the TTS character cap). One reconnect after 0.2 s, replaying the 300 ms preroll. |
| 1b | Reconnect details *(R2)*, one slice each:<br>• `test_one_drop_counts_once_when_send_and_events_both_fail` (only the reader owns reconnects; the sender marks the stream dead and waits);<br>• `test_drop_promotes_pending_partial_to_final` (no 5 s wait in `_after_endpoint`);<br>• `test_reconnect_replays_audio_since_last_final` (a ring buffer of up to 10 s; the preroll alone is cleared once STT opens);<br>• `test_settle_bills_all_stt_streams` (two streams of 3 s and 2 s → settle bills 5 s). | `session.py` and `server.live_providers` |
| 2 | `test_second_stt_drop_says_voice_limit_once` → `VOICE_LIMIT` once; typed questions still answered | — |
| 3 | **Breaker unit** (pure, fake clock) `test_breaker_transitions` with `Breaker(fail_max=5, window_s=60, open_s=30)`:<br>• 4 failures → `closed`; the 5th within 60 s → `open`;<br>• `allow()` is False until t+30 s; at t+30 s it is `half_open` and allows exactly 1 probe;<br>• a probe success → `closed` and reset; a probe failure → `open` for another 30 s;<br>• 5 failures spread over 61 s → stays `closed`.<br>Only `retryable` and `rate_limited` errors and timeouts count; `fatal` never does. | `voicecore/resilience.py` (about 60 lines). One breaker per provider kind per process, shared by every session in that process. Breakers are **injected** (`Session(breakers=…)`) and each test builds its own; there are no module globals *(R2)*. |
| 3b | `test_cancelled_half_open_probe_releases_the_breaker` *(R2)*: half-open, the probe call is cancelled by a barge-in (`CancelledError`) → the breaker returns to `open` for 30 s and is not stuck. `test_probe_timeout_counts_as_failure`: a probe running over 10 s → failure. | The outcome is recorded in `finally`, and the probe has a deadline |
| 4 | `test_open_llm_breaker_answers_busy_without_calling`: open → reply `BUSY`, `MockLLM.calls == 0`, trace `llm/breaker_open` | `_stream_answer` checks `allow()` and records the outcome |
| 5 | `test_open_stt_breaker_new_session_is_text_only`: a new session sends `VOICE_INPUT_DOWN` ("Voice input is unavailable right now; you can type your question.") once and opens no STT stream | `server.handler`; the reconnect in row 1 also checks the breaker |
| 6 | `test_open_tts_breaker_says_voice_off_and_answers_in_text` (no fallback: Cartesia credits are exhausted, see D) | reuse `VOICE_OFF` |
| 7 | `test_turn_deadline_wraps_llm_only`: the LLM trickles a token every 5 s and the 8 s stall check never fires → at 20 s `TROUBLE` and a cancel. Second test: a 30-second answer whose LLM finished in 1 s plays to the end. | `asyncio.timeout(20)` around the LLM stream only, not playback. It raises a dedicated `TurnDeadline`, which is caught **before** the stall handler, so the user hears `TROUBLE` and not `REPROMPT` *(R2)*. |
| 8 | Breaker metrics: `voicecore_breaker_state{provider}` and `voicecore_breaker_opens_total{provider}` from trace events `*/breaker_open|half_open|closed`. Run the promtool `BreakerOpen` test from Phase 5 row 7; add a runbook section. | `MetricsSink` |
| 9 | Go `TestUpstreamDialRetriesOnlyOnRefusedBeforeUpgrade` (uses 0.9 `RefuseDials` and 0.10's ECONNREFUSED): the 1st dial is refused → welcome. A dial that **times out** is not retried → 1011 (a retry could double-reserve budget). | retry once after 300 ms on refused only |
| 10 | Go `TestUpstreamBreakerFailsFastAndReadyz503` (synctest): 5 refused dials in 60 s → new sessions get 1011 with no dial for 30 s; `/readyz` 503 `{"upstream":"open"}` | `session/breaker.go` (same rules as row 3), one per upstream |
| 11 | Chaos scenarios with literal expected traces, run by `harness/gate.py`: `stt_drop.json`, `llm_breaker.json` (5 × 429s → breaker open → `BUSY`) | `chaos.build()` supports `error_after_ms` and repeated LLM errors |
| 12 | Optional live check (about $0.05, asked at the step): `pytest -m live` provider contracts | pass |

## Phase 7 — Abuse protection and hardening (~10 h, seams 2, 13, 19; skills `cso`, `security-review`)

| # | RED test (literal) | GREEN |
|---|---|---|
| 1 | Go `TestTurnstile`:<br>• secret set, no form field `cf-turnstile-response` → 403;<br>• fake siteverify `success:false` → 403, `success:true` → 200 with a token;<br>• siteverify takes more than 2 s → 503;<br>• body over 4 KiB → 413.<br>Only new sessions are challenged; a resume uses `resume_key`. | `-turnstile-secret` / env `TURNSTILE_SECRET`; `-turnstile-url` for tests. A form field keeps it a CORS "simple request" (no preflight). `http.MaxBytesReader`. |
| 2 | Go `TestCORSEchoesOnlyAllowedOrigin` | replaces `*` |
| 3 | Go (seam 19) `TestValidateProd`: returns errors unless all of these hold:<br>• `GATEWAY_SECRET` ≥ 32 bytes;<br>• Turnstile secret set;<br>• origins and hosts without localhost;<br>• trusted proxies set;<br>• `-redis-url` set when copies > 1.<br>The error lists every missing item. | `Config.ValidateProd()`; `main.go -env prod` exits 1 on any error |
| 4 | Go `TestDebugCountersNotOnPublicMux` → 404 (admin listener only) | — |
| 5 | Playwright `csp.spec.ts`: load the docs site and the demo, open the widget, run one mock turn; a `securitypolicyviolation` listener records 0 violations. Headers are present: CSP, `X-Content-Type-Options`, `Referrer-Policy`, `frame-ancestors 'none'`. | `apps/docs/nginx.conf` and the demo nginx config. CSP allows the gateway origin (`connect-src`), `challenges.cloudflare.com`, Google Fonts, and Docusaurus's inline theme script via its sha256 hash (computed in the docs build, written by a tiny post-build script) |
| 6 | CI hardening:<br>• `.github/dependabot.yml` (gomod, uv, npm, docker, github-actions);<br>• gitleaks **binary** (the Action needs a licence for org repos): custom rules for the 3 key prefixes; scans **everything, including `benchmarks/raw/**`** (where a leaked key would most likely land); known false positives listed by fingerprint in `.gitleaksignore` *(R2)*; blocking;<br>• `govulncheck` blocking;<br>• `pip-audit` (`uv export \| pip-audit -r - --ignore-vuln-file …`), `pnpm audit --prod --audit-level high` and `grype` (only fixed vulnerabilities, ignore file) as **non-blocking** jobs on push plus a weekly schedule, so a new upstream CVE never turns main red;<br>• all actions pinned by SHA;<br>• `timeout-minutes` and `concurrency` on every job;<br>• the docker-heavy jobs (`compose`, `monitoring`, `scale`, `fly-image`) run on `main`, and on PRs only when `paths:` match their files *(R2: CI minutes on a private repo)*. | green on main |
| 7 | `docs/ops/key-rotation.md`: per provider, where to make a new key, `fly secrets set`, `.env`, how to verify, how to revoke the old one | doc only |
| 8 | `cso` on the phase diff, then `security-review` | 0 open high findings |

## Phase 8 — Widget: reconnect and Turnstile UI (~5 h, seam 13; skills `ui-taste`, `qa`)

| # | RED test (literal) | GREEN |
|---|---|---|
| 1 | vitest `client.test.ts`:<br>• the socket closes → reconnects to `/v1/ws?resume=<id>` with `{session_id, resume_key}` (the token is not reused alone) within 10 s, then plays the next generation;<br>• 3 failed attempts → `socket.closed`. | `VoiceClient` retries at 0.5, 1 and 2 s. The `?resume=` query is used by the multi-copy load balancer (Phase 10). |
| 2 | Playwright: abort the connection mid-session → status "Reconnecting…", then "Ready" | widget states |
| 3 | Playwright with `page.route("https://challenges.cloudflare.com/**")` stubbing the Turnstile script:<br>• always-pass → session;<br>• always-fail → "Couldn't verify you're human. Reload and try again." | `data-turnstile-sitekey`. Turnstile is off when the attribute is missing (default compose and `smoke.py` unaffected). |
| 4 | `qa` with mocks; screenshots of each state | fixes |

## Phase 9 — Public budget pool and quotas (~4 h, seams 10, 18, 2)

`public` is a **sub-cap inside the same ledger lock as `usd`**. The $5 hard cap holds, and `factory.py`'s pool guard is unchanged.

| # | RED test (literal) | GREEN |
|---|---|---|
| 1 | `test_public_counts_in_usd_and_public`: reserve 0.10 with `sub="public"` → `total("usd")` 0.10, `total("public")` 0.10 | `reserve(pool, amount, sub=None)` |
| 2 | `test_public_daily_cap`: caps `public {total 2.00, daily 0.50}`, `budget.now` injected; 0.45 + 0.10 on the same day → refused; the next day → allowed | daily sum from `ts` (Phase 0.4) |
| 3 | `test_cap_hit_switches_to_text_only_extractive_mode` *(R2: the mock LLM would give a wrong canned answer with real citations)*. Daily cap reached:<br>• the first reply is "Today's voice demo budget is used up. I can still point you to the right page: ask a question by typing.";<br>• the mic is ignored (no STT);<br>• each typed question gets `Closest section: <title>.` plus `answer.sources` with that one passage (so the widget opens it);<br>• no LLM call, no TTS. | `voicecore/answer/extractive.py`: top hit from `Index.search`. Uses `reply=` generations (no protocol change). |
| 4 | Go `TestPerIPDailyQuota[mem]`: 21st POST from the same IP the same day → 429 (`-sessions-per-ip-per-day 20`) | `session/store.go` interface (`memStore` now, `redisStore` in Phase 10). With `memStore` a cold start resets the count, which is documented; Turnstile, the token bucket and the dollar caps still bound spend. |
| 5 | `--pool usd\|public` flag (default `usd`) | — |

## Phase 10 — Multi-copy scaling and load (~18 h, seams 18, 2, 9b; skills `benchmark`, `careful`)

**Goal:** `docker compose --profile scale up` runs 2 gateways and 2 orchestrators behind nginx, with shared state in Redis. Prove that sessions spread, resume sticks to the right copy, a dead copy loses no new sessions, and spend stays exact.

| State | Multi-copy answer |
|---|---|
| Budget ledger | `RedisStore`: one Lua script does check-and-reserve (`usd` cap, `public` sub-cap, daily cap) atomically, storing **integer micro-dollars** *(R2)*. `VOICECORE_LEDGER=redis://…` selects it; `FileStore` stays the default. Redis runs with **AOF on and a volume** *(R2)*. `RedisStore` refuses to start on an empty store until `python -m voicecore.budget migrate --from benchmarks/spend_ledger.json --to redis://…` has seeded the totals, so the $5 cap can never restart at $0. |
| Token nonces | Redis `SET n NX EX 60` |
| Per-IP daily quota | Redis `INCR quota:{ip}:{day}` + `EXPIRE 86400` |
| Per-IP token bucket | stays per copy (documented: the effective limit is N × 10 per minute) |
| Sessions and resume | stay in the owning gateway. The session id carries its copy id (`s-gw1-…`, Phase 3 row 7). The SDK reconnects to `/v1/ws?resume=<id>`, and nginx `map $arg_resume` on the prefix (`~^s-gw1-` → gw-1) sends it to the **owner** *(R2: a hash would hit a random copy)*. New sessions are round-robin. On Fly the gateway answers a resume for another machine with `fly-replay: instance=<machine id>`; the copy id is the Fly machine id (check with Context7). |
| Which orchestrator | `-upstream ws://orch-1:8765,ws://orch-2:8765`. Each new session goes to the ready upstream with the fewest of this gateway's sessions; **ties rotate** *(R2)*. `/readyz` is polled every 2 s, a handshake 503 tries the next upstream, and each upstream has its own breaker. A session stays on its upstream for life. |
| Breakers, docs index, VAD | per process, deliberately |
| Redis down | ledger and nonces **fail closed** (new sessions refused, `session.ended{unavailable}`); quotas fail open with a warning log |

| # | RED test (literal) | GREEN |
|---|---|---|
| 1 | Seam 18 (Python):<br>• `test_concurrent_reserves_never_exceed_cap[file\|redis]`: 100 tasks × $0.01 against $0.50 left → exactly 50 succeed, total 0.50;<br>• `test_public_daily_cap[file\|redis]`;<br>• `test_orphans[file\|redis]`;<br>• `test_redis_down_fails_closed[redis]` (stop the container → `reserve` raises `BudgetUnavailable`);<br>• `test_redis_store_refuses_unseeded` → `BudgetUnavailable("ledger not seeded")`; after `migrate`, `total("usd")` equals the file ledger's total;<br>• **the concurrency test uses a `ProcessPoolExecutor` with 8 workers** *(R2: `reserve` is synchronous, so asyncio tasks would run one at a time and pass without any lock)*. | `voicecore/budget_store.py`: `FileStore` (today's code moved) and `RedisStore` (redis-py `register_script`). `budget.py` keeps its API. |
| 2 | Seam 18 (Go): `TestNonceSingleUse[mem\|redis]`, `TestDailyQuota[mem\|redis]` | `session/store.go` `redisStore` (go-redis); `-redis-url` |
| 3 | Go `TestPicksLeastLoadedReadyUpstream`: A has 2 of our sessions, B 0 → next goes to B; B `/readyz` 503 → A | `session/upstream.go` |
| 4 | Go `TestOrchestratorDeathOnlyEndsItsSessions`: kill fakeorch A → A's sessions get `session.ended{error}`; B's continue; the next new session goes to B | existing `end("error")` |
| 5 | Compose profile `scale`:<br>• `redis:7` with `--appendonly yes` and a named volume;<br>• `orch-1` and `orch-2` (`VOICECORE_LEDGER=redis://redis`, `--providers mock-billed` *(R2)*);<br>• `gw-1` and `gw-2` (shared `GATEWAY_SECRET`, `-copy-id gw1` / `gw2`, `-redis-url`, the upstream list, `-max-sessions-per-ip 0 -tokens-per-minute 0 -sessions-per-ip-per-day 0`, because every test client shares one IP *(R2)*);<br>• `lb`: nginx `deploy/scale/nginx.conf` with WebSocket upgrade; `/v1/ws` uses `map $arg_resume` on the copy prefix → the owner, with no `resume` → round-robin; `/v1/session` is round-robin. A `seed` one-shot service runs `budget migrate` before the orchestrators start.<br>`compose --profile scale config --quiet` in CI. | — |
| 6 | `test_scale_profile` (docker, CI job `scale`, mocks), polling deadlines 60 s:<br>(a) 40 sessions through `lb` → each orchestrator's `voicecore_sessions_total` is 20 ± 8;<br>(b) a client that drops and reconnects within 10 s gets `resumed:true` on the same gateway;<br>(c) `docker compose stop orch-1` mid-run → every client still ends with an answer or a clean `session.ended`, and new sessions go to `orch-2`;<br>(d) the Redis ledger total increases by exactly 40 × $0.0017 = $0.068 (billed mocks, row 0.13) *(R2: plain mocks reserve nothing, so the old check was 0 = 0)*. | — |
| 7 | **Mock load** via `wss.py --parallel N` through `lb`: N = 20, 50, 100 on 1 copy and on 2 copies. `start_stack` passes `-max-sessions 0`, `-max-sessions-per-ip 0`, `-tokens-per-minute 0`, `-sessions-per-ip-per-day 0` (all clients share one IP). Read `voicecore_event_loop_lag_ms` p99, server stage p95, CPU and RSS from `/metrics`. **Rule:** if loop-lag p99 > 50 ms at 50 sessions on one copy, move VAD to `ThreadPoolExecutor(2)` (ponytail note at `server.py:112`) and re-measure before and after. | `reports/load.md`, labelled `fake-provider` |
| 8 | **Live load test** (`careful`; confirm about $0.16 at the step):<br>• `harness/build_local_fixtures.py --key fixtures/docs/voicecore_key.json` speaks the 12 `answer` questions with `aura-2-apollo-en` into `fixtures/audio/local/voicecore/` (local only, gitignored, about $0.01). This needs its own slice first *(R2)*: `--key` reads the `cases`/`turns` format, clip ids are `vc_a01…` (no collision with existing ids), and it writes `local/voicecore/manifest.json`; `wss.py`'s `all_clips()` then reads every `local/**/manifest.json`. RED: `test_voicecore_key_produces_vc_clip_ids` (with the TTS call mocked);<br>• `wss.py --providers live --parallel 5` × 2 rounds on 1 copy.<br>Pass: 10/10 answered, 0 gateway drops; any 429 is recorded. | `reports/load.md` live rows (`live-provider`): p50/p95 total, stages, errors, cost per turn from the ledger |
| 9 | Soak (`workflow_dispatch` job plus one recorded local run; not scheduled, to save CI minutes): scale profile, 30 min, 10 mock sessions looping. RSS growth < 10% per process; goroutines, file handles and Redis memory flat. | `reports/load.md` |
| 10 | ADR 0004 "multi-copy" section: the table above, the fail-closed and fail-open choices, the measured ceilings | — |

## Phase 11 — Deploy, ready but not run (~7 h, seams 15, 19)

Fly app `voicecore`:
- **Machine.** One `shared-cpu-1x` with 1 GB in `iad`. One image runs both the gateway (public :8080) and the orchestrator (:8765).
- **Entrypoint (ordered shutdown, R2).** `deploy/fly/entrypoint.sh` runs under plain `tini` (no `-g`, which would signal both at once and kill bash).
  - It traps TERM: send TERM to the gateway and wait for its drain (25 s, which ends every session), then send TERM to the orchestrator (drain 10 s, normally nothing left), then exit.
  - If either process dies on its own, `wait -n` returns and the script exits non-zero, so Fly restarts the machine.
- **`fly.toml` settings:**

  | Setting | Value / purpose |
  |---|---|
  | `kill_signal` | `"SIGTERM"`; Fly's default is SIGINT |
  | `kill_timeout` | `45` (25 s + 10 s + margin) *(R2)*; Fly's default is 5 s, which kills the drain |
  | `[http_service]` | internal_port 8080, `auto_stop_machines = "stop"`, `auto_start_machines = true`, `min_machines_running = 0` |
  | checks | `GET /readyz` |
  | `[[metrics]]` | two entries: orchestrator :9464 and gateway admin :9091 (both bound to 0.0.0.0 and not public) |
  | `[mounts]` | a `voicecore_data` volume at `/data` for `VOICECORE_LEDGER=/data/spend_ledger.json` |

- **Secrets.** `DEEPGRAM_API_KEY`, `OPENROUTER_API_KEY`, `GATEWAY_SECRET`, `TURNSTILE_SECRET`.
- **Flags.** `-env prod`, `--pool public`, `-trusted-proxies <Fly proxy range, looked up at deploy time>`.
- **Prod start checks.** Startup fails unless the ledger path is on a mounted volume: `/data` exists, is writable, and is a different device from `/`. So spend caps cannot reset on a cold start.
- **Deploy preconditions in the guide:**
  - set an OpenRouter key credit limit;
  - use a dedicated Deepgram project key with usage alerts;
  - the volume costs a few cents a month.
- **Docs site.** The existing nginx image; the guide covers a second small Fly app or any static host.
- **Scale to 2.** `fly scale count 2`, Redis in `VOICECORE_LEDGER` and `-redis-url`, `fly-replay` for resume. Documented, not deployed.

| # | RED test / check | GREEN |
|---|---|---|
| 1 | `test_prod_refuses_ledger_on_image_fs`: `--env prod` with `VOICECORE_LEDGER=/app/x.json` (same device as `/`) → exit 1 with `ledger must be on a mounted volume` | orchestrator prod checks |
| 2 | `flyctl config validate -c deploy/fly/fly.toml` (in CI if it needs no auth, otherwise run locally and record) | `deploy/fly/fly.toml` |
| 3 | `test_fly_image` (docker, CI):<br>• build, run with a tmp volume → `/readyz` 200 within 20 s;<br>• run with `-env dev` (no Turnstile) for the answer check: `smoke.py --gateway http://localhost:<port>` gets a cited answer;<br>• `docker kill -s SIGTERM` during a mock session → `session.ended{shutdown}`, the gateway exits first, then the orchestrator, exit 0 within 45 s;<br>• kill the orchestrator process → the container exits non-zero. | `deploy/fly/Dockerfile` (multi-stage) and `entrypoint.sh` |
| 4 | `docker-compose.prod.yml` overlay (`config --quiet` in CI):<br>• images pinned by digest;<br>• the ledger on a named volume;<br>• no `--trace-dir`;<br>• agent-core not published;<br>• `LOG_FORMAT=json`;<br>• `-env prod`. | overlay |
| 5 | `.github/workflows/deploy.yml`, `workflow_dispatch` only, needs a `FLY_API_TOKEN` the user adds later. Steps: `flyctl deploy --remote-only -c deploy/fly/fly.toml`, wait for `/readyz`, then a **prod smoke** *(R2: prod requires Turnstile, so a full answer can't be fetched there)*: `/readyz` 200, `POST /v1/session` without Turnstile → 403, `/debug/counters` → 404. The full answer path is covered by `test_fly_image`. | exists, never run |
| 6 | Canary: `harness/smoke.py --gateway <url>`; the CI compose job runs daily (`schedule:`, about 10 minutes a day). `canary` skill once against local compose. | green |
| 7 | `docs/ops/deploy.md`:<br>• commands (`fly apps create voicecore`, `fly volumes create voicecore_data --size 1`, `fly secrets set …`, `fly deploy -c deploy/fly/fly.toml`);<br>• preconditions;<br>• cost (idle about $0 plus the volume; check pricing at deploy time);<br>• rollback (`fly releases`, `fly deploy --image <previous>`);<br>• scaling to 2 copies;<br>• turning on the public pool and Turnstile. | — |

## Phase 12 — Privacy page and wrap-up (~3 h)

| # | Do | Check |
|---|---|---|
| 1 | `apps/docs/src/pages/privacy.md` (not ingested): what is stored and for how long, **per deployment** *(R2)*: local compose keeps logs 7 days in Loki (compactor); Fly keeps logs per Fly's own log retention, with no Loki there (check and state the figure); traces are off in prod; the ledger holds amounts, never text. Also what each provider receives. Widget link "Privacy" (`data-privacy-url`). | Playwright: link present, opens `/privacy` |
| 2 | Update `reference/configuration.md` (new flags) and `getting-started/embed-the-widget.md` (Turnstile, reconnect, privacy attributes). Anchor check: 0 broken. Optional assistant-eval re-run (about $0.02, asked) stays ≥ 18/22. | — |
| 3 | README "Operations" section; `EXECUTION_STATUS.md`; step-09 registers and handoff | — |
| 4 | `code-review` (high) on all of Step 09, then `health`, then `document-release` | findings fixed |

---

## Order

0 → 1 → 2 → 3 → 4 → 5 → 6 → 7 → 8 → 9 → 10 → 11 → 12

| Phase | Depends on |
|---|---|
| 3 (resume key, IP tokens) | 0.6 (memnet addresses) |
| 4 (logs with session ids) | 3 |
| 5 (metrics) | 4 (logs feed Loki), and its own trace events (0a, 0b) |
| 6 (breaker metrics and alert) | 5 |
| 7 (Turnstile) | 3 (resume bypass) |
| 8 (widget) | 3, 7 |
| 9 (quota) | 3 (client IP) |
| 10 (multi-copy) | 3, 6, 8 (resume URL), 9 |
| 11 (deploy) | 2, 5, 7, 9 |

Roughly 110 hours in total.

## Verification (whole plan)

- **CI green:** go, python, ts, e2e, docs, compose (healthchecks, smoke, CSP spec), monitoring (promtool, amtool, alert-to-sink, turn count), scale (scale-profile test), security (gitleaks, govulncheck blocking; pip-audit, pnpm audit and grype non-blocking), and the deploy config.
- **Monitoring profile:** Grafana shows turns. Stopping agent-core puts `OrchestratorDown` firing, then resolved, in the `alert-sink` logs.
- **Graceful stop:** SIGTERM during a session lets it finish; nothing is left `reserved`; `/readyz` returns 503 while draining. The same holds in the Fly image.
- **Gate:** `harness/gate.py` passes the STT-drop and LLM-breaker chaos scenarios. Breaker unit and integration tests pass.
- **Scale profile:** sessions split across both orchestrators, resume sticks, a dead orchestrator loses no new sessions, and the Redis ledger total is exact.
- **`reports/load.md`:** mock rows (1 and 2 copies × 20/50/100) and the live row (5 × 2).
- **`docs/ops/`:** data map, targets, runbooks, incident template plus 2 write-ups, deploy guide, key rotation.
- **Spend:** ≤ $0.25 above the start of Step 09, checked in the ledger.

## Not in this plan (user decides later)

- Running the Fly deploy, the real Turnstile key and Cloudflare account, and real Slack or email receivers. The config supports them, switched off.
- Rotating the API keys and making the repo public.
- Trace pruning (traces are off in prod) and docs index hot-reload (the corpus is baked in at build).
