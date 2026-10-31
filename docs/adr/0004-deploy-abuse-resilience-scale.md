# ADR 0004: Deploy, abuse protection, resilience and scale

**Status:** Accepted for lifecycle, session security, resilience, abuse and multi-copy (Step 09 phases 2–10, 2026-10-30). The deploy section is proposed until Phase 11. [Plan](../PRODUCTION_PLAN.md); evidence in the [step 09 registers](../step_09_production_readiness.md).

## Lifecycle

- **Health checks.** `/healthz` means alive. `/readyz` means "send me new users": the orchestrator after its VAD and docs index load; the gateway while not draining and while at least one orchestrator's breaker allows a dial.
- **Drain.** On SIGTERM both services drain for up to 25 s: no new sessions, open ones finish, then `session.ended{shutdown}`, budgets settle, exit 0. A combined image stops the gateway first, then the orchestrator.
- **Health probe without curl.** The distroless gateway probes itself (`-probe`).

## Session security

- **Resume.** It needs the 64-hex `resume_key` from `welcome`; a session id alone is not enough.
- **Tokens.** `exp.nonce.HMAC(exp.nonce.ip)` tokens are single-use and bound to the client IP. A resume skips the token, so a spent token still reconnects.
- **Client IP.** `X-Forwarded-For` counts only from `-trusted-proxies`, using the rightmost untrusted hop.

## Resilience

- **STT drops.** One STT reconnect per session after a drop, replaying the audio since the last final (≤ 10 s). If the turn already ended, the partial transcript is promoted instead. A second drop means text only.
- **Breakers.** One per provider per orchestrator, and one per upstream in the gateway.
  - Five counted failures within 60 s open one for 30 s; then one probe goes out.
  - Only the probe's success closes it; no verdict within 10 s reopens it.
  - Fatal errors and our own bugs are no verdict.
- **Turn deadline.** The LLM part of a turn is limited to 20 s; playback never is.
- **Gateway dial.** A refused dial is retried once after 300 ms. A timed-out dial is never retried, because it may have reserved budget.

## Abuse

- **Human check.** Turnstile on new sessions only; resumes are proven by their key.
- **Origins.** CORS on the token endpoint applies the WebSocket's origin rules.
- **Production config.** `-env prod` refuses to start without the production settings.
- **Spend.** A `public` sub-cap inside the $5 pool: $2 in total, $0.50 per UTC day. Over it, sessions answer in text with the closest docs section and no provider call.
- **Per-address quota.** A daily token quota per address, charged only after the human check.

## Multi-copy (Phase 10)

| State | Where | Why |
|---|---|---|
| Budget ledger | Redis (`VOICECORE_LEDGER=redis://`), integer micro-units, one Lua script for check-and-reserve | Copies must never jointly pass a cap. AOF on a volume. The store refuses to work until seeded from the file ledger, so the cap never restarts at $0. |
| Used token nonces | Redis `SET NX EX` (`-redis-url`) | A token must start one session across all copies. |
| Daily quota per address | Redis `INCR` with a 48 h expiry | The quota is per address, not per copy. |
| Token bucket per address | per copy | Effective limit N × 10 per minute. Documented; Turnstile and the caps bound spend. |
| Sessions and resume | the owning gateway | The session id carries the copy id (`s-gw1-…`). The SDK reconnects to `/v1/ws?resume=<id>`, and nginx's `map $arg_resume` sends it to the owner; everything else is round robin. On Fly the plan is `fly-replay` (Phase 11). |
| Which orchestrator | the gateway's choice | `-upstream a,b`: the fewest of this gateway's sessions, ties rotate. Skip one that answers 503, refuses or has an open breaker. A session stays on its orchestrator for life. |
| Breakers, docs index, VAD | per process | Deliberately: each process judges its own view of a provider. |

**Failure choices:**

- **Ledger or nonces unreachable: fail closed.** New sessions are refused (orchestrator `BudgetUnavailable`: `session.ended{error}`, logged with reason `ledger_unavailable`, even in the public pool, where a used-up budget would give text-only answers; gateway 1013). Letting spend through blind, or a reused token in, is worse than a refused session.
- **Quota store unreachable: fail open, with a warning log.** Turnstile, the token bucket and the dollar caps still bound spend.

**Measured ceilings (`fake-provider`, one laptop running clients and servers; [reports/load.md](../../reports/load.md)):**

- One orchestrator holds 50 concurrent voice sessions with event-loop lag p99 under 5 ms and latency unchanged.
- At 100 on one orchestrator, lag p99 reaches 445 ms and p95 passes the 1,200 ms target.
- Two copies answer all 100.
- The rule for moving VAD to a thread pool (lag p99 > 50 ms at 50 sessions) was not triggered.

## Deploy (proposed, Phase 11)

- **Fly app `voicecore`**, deployed 2026-10-31 ([deploy guide](../ops/deploy.md)): one machine running the gateway and the orchestrator.
- **Signals.** `kill_signal` SIGTERM and `kill_timeout` 45 s, for the ordered drain.
- **Ledger.** It lives on a mounted volume; prod refuses to start without one.
- **Deploying** needs the user's go-ahead.
