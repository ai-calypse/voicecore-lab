# Step 09: Production Readiness

**Status:** In progress (started 2026-10-30). Phases 0–1 done; Phase 2 (health and drain) next.
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
| 2026-10-30 | — | Commit attribution removed from all history (user request); project settings disable it from now on | `.claude/settings.json`; `git log --format=%B \| grep -ci co-authored` = 0 |

## Execution record

| Date | Phase | Commands and results |
|---|---|---|
| 2026-10-30 | 0 | `uv run pytest -m "not live and not docker"`: 131 passed. `go test -race ./...`: ok. `pnpm --filter @voicecore/demo test`: 3 passed. `pnpm --filter @voicecore/demo e2e`: 11 passed. `pnpm --filter @voicecore/docs e2e`: 2 passed. |

## Source and artifact change record

| Date | Paths | Why |
|---|---|---|
| 2026-10-30 | `conftest.py`, `voicecore/budget.py`, `harness/baseline_deepgram.py` | ledger safety |
| 2026-10-30 | `services/realtime-gateway/internal/{memnet,fakeorch}` | test helpers |
| 2026-10-30 | `voicecore/providers/mock.py`, `voicecore/server.py`, `pyproject.toml`, `Makefile`, `ci.yml` | mock drop, docker marker, billed mocks |
| 2026-10-30 | `apps/demo/{playwright.config.ts,vitest.config.ts,e2e/*,public/embed-test.html,package.json}`, `apps/docs/playwright.config.ts` | e2e isolation |

## Handoff

Not yet. The step ends when the acceptance checklist is complete. The user then decides on deploying, the real Turnstile and paging credentials, and key rotation.
