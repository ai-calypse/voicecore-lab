# ADR 0004: Deploy, abuse protection, resilience and scale

**Status:** Proposed (stub, 2026-10-30). Filled in by Step 09 phases 2, 3, 6, 7, 9, 10 and 11 ([plan](../PRODUCTION_PLAN.md)).

## Sections to fill

- Lifecycle: health, readiness, drain order (gateway then orchestrator), timeouts.
- Session security: resume key, single-use IP-bound tokens, trusted proxies.
- Resilience: STT reconnect, circuit breaker rules, per-turn deadline, dial retry policy.
- Abuse: Turnstile on new sessions only, quotas, the public sub-pool.
- Multi-copy: what is shared in Redis, what stays per copy, sticky resume by copy prefix, fail-closed and fail-open choices, measured ceilings.
- Deploy: Fly app config (ready, not deployed), volume for the ledger, signals and kill timeout.
