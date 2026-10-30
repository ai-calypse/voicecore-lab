# Incident process

**Status:** Step 09 Phase 5, 2026-10-30. Written for a one-person project; the roles still apply when there is a second person.

## Severity

| Level | Meaning | Example | Write-up |
|---|---|---|---|
| **SEV1** | Voice is down for everyone | the gateway or orchestrator is down; every session ends in `error` | required, within 2 days |
| **SEV2** | Degraded for many | speech stops mid-answer; p95 latency far over target; a provider failing | required, within 5 days |
| **SEV3** | Cosmetic or one user | a wrong citation link; a typo in a fixed reply | optional |

## Roles

- **Incident lead:** decides, keeps the timeline and calls the incident over. With one person, that person.
- **Fixer:** works on the problem and reports to the lead. With one person, the same person, so keep the timeline as you go.

## What to do

1. Note the time (UTC) and what you saw. Start the timeline in a new file copied from [the template](incidents/TEMPLATE.md).
2. Stop the bleeding first: stop live providers (`PROVIDERS=mock`), or scale to zero, before you understand the cause. Money and users come before the fix.
3. Follow the alert's runbook in [runbooks.md](runbooks.md).
4. When it is fixed, check it is fixed: the alert resolves, a smoke test answers.
5. Write it up: what happened, why, and what changes. Blameless: describe the system and the decisions, not a person's fault.

## Write-ups

- [2026-10-30: speech stopped after about six answers](incidents/2026-10-30-tts-session-cap.md) (SEV2)
- [2026-10-30: a benchmark measured the wrong stack](incidents/2026-10-30-benchmark-hit-wrong-stack.md) (SEV3)
