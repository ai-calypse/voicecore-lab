# 2026-10-30: a benchmark measured the wrong stack

**Severity:** SEV3 (internal: wrong measurements, no users). **Status:** final. **Lead:** project owner.

## Summary

While tuning latency, a WSS benchmark run measured a Docker Compose stack left running on `127.0.0.1:8080` instead of the stack the runner had just started. The runner's own gateway could not bind the port and exited, but the clients still connected to `:8080` and got answers, so the run looked normal. The runner now checks that the processes it started are still alive before it sends traffic.

## Impact

- Benchmark numbers from the affected run described a different build. They were not used in any report. The exact number of affected runs was not recorded.
- A related risk was found later: the end-to-end tests also reused whatever answered on their ports, which could have been a live, paid stack. Step 09 Phase 0 moved them to their own ports.

## Detection

Noticed by the owner during the latency work; how exactly was not recorded. Nothing automatic caught it, which is the problem the action items fix.

## Timeline (UTC)

| Time | Event |
|---|---|
| before 13:48 (not recorded) | a latency run measures the leftover stack |
| 13:48 | fix committed with the latency work: the runner fails fast when a process it started has exited, for example because a Docker stack holds `:8080` ([8e2f982](https://github.com/ai-calypse/voicecore-lab/commit/8e2f982)) |
| 17:39 | the runner also waits on the orchestrator's `/readyz` and stops if the process dies ([e112cef](https://github.com/ai-calypse/voicecore-lab/commit/e112cef)) |

## Root cause

- The runner started its stack on the same fixed ports as the developer stack and Docker Compose, and assumed that whatever answered on the port was its own.
- A failed bind is an early exit of a child process, which the runner did not watch.

## What went well, and what did not

- Went well: it was caught before any number from it reached a report.
- Did not: "something answered" was treated as "my process answered".
- Unknown: whether the leftover stack used live providers was not recorded.

## Action items

| Action | Owner | Link | Status |
|---|---|---|---|
| Runner fails fast if a process it started has exited | owner | [8e2f982](https://github.com/ai-calypse/voicecore-lab/commit/8e2f982) | done |
| Runner waits on `/readyz` of its own orchestrator and watches it | owner | [e112cef](https://github.com/ai-calypse/voicecore-lab/commit/e112cef) | done |
| E2E tests on their own ports, never reusing a server, and refusing a live orchestrator | owner | [Step 09 Phase 0](../../step_09_production_readiness.md) | done |

## Blameless note

Fixed ports shared between a benchmark and a dev stack make this easy to hit. The fix is in the runner, not in remembering to stop stacks.
