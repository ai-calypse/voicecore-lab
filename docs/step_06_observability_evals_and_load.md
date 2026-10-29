# Step 06: Observability Evals And Load

**Status:** Planned; no implementation or test evidence yet.  
**Estimated engineering effort:** 40 hours.  
**Task owner:** Implementation agent; user confirms external paid credentials.  

## Purpose and scope

Build an inspectable voice lab, not merely an attractive demo. Focus on ownership and evidence, not cosmetic product polish. Follow the global project non-goals in [master plan](./voicecore_lab_career_aligned_plan.md#explicit-non-goals).

## Step-specific implementation-agent prompt

> Act as a senior real-time voice software engineer. Read this step, the canonical [plan](./voicecore_lab_career_aligned_plan.md), [process](./README.md#source-of-truth-and-change-detection), and referenced previous step outputs. Inspect the existing code and prior execution records. Implement all remaining tasks in dependency order, verify with real commands and tests, record actual evidence/paths, and stop at this step's exit gate. Never invent pass results, provider support, latency numbers or source files.

## Required reading and prerequisites

- [Master architecture and contracts](./voicecore_lab_career_aligned_plan.md#system-architecture)
- [Previous step](./step_05_barge_in_and_recovery.md) and its actual outputs, not merely planned files.
- Exact upstream code artifacts and ADRs named in the tasks below; if missing, record blocker and do independent preparations only.

## Decision ownership

This step owns the task-specific implementation choices, contracts and test evidence described below. It inherits the public goals, constraints, budget philosophy, evaluation thresholds and overall stack from the master plan. Do not silently change cross-step contracts. If needed, update the responsible upstream ADR/document and mark affected work for review.

## Phases and specific tasks

### S06-T01 — Trace schema

**Outcome / implementation:** Define trace IDs across client/Go/Python/STT/LLM/TTS, redact speech content by default.  
**Inputs:** This document, [master](./voicecore_lab_career_aligned_plan.md), current upstream records and working code.  
**Dependencies:** None beyond prerequisites.  
**Expected artifacts:** `packages/protocol/tracing and services/telemetry` (planned; actual paths may be selected in owner register).  
**Edge/failure concerns:** Handle invalid input, task cancellation, empty data and path/session lifecycle where applicable; explicitly mark any scenario that is genuinely not applicable.  
**Acceptance test:** Trace exemplars reconstruct each turn without retaining raw audio.  

### S06-T02 — Live timeline UI

**Outcome / implementation:** Create development timeline with stage bars, microphone/agent speaking states and dropped frames.  
**Inputs:** This document, [master](./voicecore_lab_career_aligned_plan.md), current upstream records and working code.  
**Dependencies:** S06-T01.  
**Expected artifacts:** `apps/lab-ui` (planned; actual paths may be selected in owner register).  
**Edge/failure concerns:** Handle invalid input, task cancellation, empty data and path/session lifecycle where applicable; explicitly mark any scenario that is genuinely not applicable.  
**Acceptance test:** Reviewer can visually identify bottleneck and an interrupted generation.  

### S06-T03 — Scenario simulator

**Outcome / implementation:** Feed prerecorded audio with wall-clock pacing; support silence, noise, barge-in, network faults and parallel users.  
**Inputs:** This document, [master](./voicecore_lab_career_aligned_plan.md), current upstream records and working code.  
**Dependencies:** S06-T02.  
**Expected artifacts:** `harness/scenarios` (planned; actual paths may be selected in owner register).  
**Edge/failure concerns:** Handle invalid input, task cancellation, empty data and path/session lifecycle where applicable; explicitly mark any scenario that is genuinely not applicable.  
**Acceptance test:** Repeatable scenario produces structured output with deterministic conditions.  

### S06-T04 — Performance evaluation

**Outcome / implementation:** Report true time-to-first-audio, user endpoint delay, p50/p95/p99, drop rate and cost/turn.  
**Inputs:** This document, [master](./voicecore_lab_career_aligned_plan.md), current upstream records and working code.  
**Dependencies:** S06-T03.  
**Expected artifacts:** `benchmarks/voice_bench.py` (planned; actual paths may be selected in owner register).  
**Edge/failure concerns:** Handle invalid input, task cancellation, empty data and path/session lifecycle where applicable; explicitly mark any scenario that is genuinely not applicable.  
**Acceptance test:** No simulated client/server clocks merged without sync method; raw CSV/JSON included.  

### S06-T05 — Quality evaluation

**Outcome / implementation:** Score transcription WER, task correctness, unsupported-answer refusal, cited-source validity and interruptions.  
**Inputs:** This document, [master](./voicecore_lab_career_aligned_plan.md), current upstream records and working code.  
**Dependencies:** S06-T04.  
**Expected artifacts:** `harness/evaluators` (planned; actual paths may be selected in owner register).  
**Edge/failure concerns:** Handle invalid input, task cancellation, empty data and path/session lifecycle where applicable; explicitly mark any scenario that is genuinely not applicable.  
**Acceptance test:** Human audited subset; model-as-judge not treated as sole truth.  

### S06-T06 — Load + regression gates

**Outcome / implementation:** Test 1/5/20/40 sessions with fake and one small real-provider profile; add GitHub Actions smoke gate.  
**Inputs:** This document, [master](./voicecore_lab_career_aligned_plan.md), current upstream records and working code.  
**Dependencies:** S06-T05.  
**Expected artifacts:** `reports/load_test.md; .github/workflows/evals.yml` (planned; actual paths may be selected in owner register).  
**Edge/failure concerns:** Handle invalid input, task cancellation, empty data and path/session lifecycle where applicable; explicitly mark any scenario that is genuinely not applicable.  
**Acceptance test:** No claims of scale beyond tested limits and provider quotas; threshold regressions fail CI.  

## Risks, verification and recovery

Require both deterministic tests and controlled real-provider measurements where applicable. Preserve inputs, command, environment, provider/version, start time, raw test outputs and known failures. Treat a mock success as **only** a mock success. On vendor/rate-limit failure, complete isolated tests and record a blocked live-provider gate. Do not hide actual errors by weakening assertions.

## Acceptance checklist

- [ ] All task outputs exist and links/commands resolve.
- [ ] Documented negative/race/failure cases pass (or have explicit open issues).
- [ ] No invented benchmark measurements or live API claims.
- [ ] Owning contracts and downstream impact reviewed.
- [ ] Tasks have evidence and source revision records.

## Decisions and outputs register (fill in during implementation)

| Decision / rationale | Owner/source section | Actual code/config location | Evidence path | Status |
|---|---|---|---|---|
| TBD | This step | TBD | TBD | Unstarted |

## Execution record

| Task ID | Status | Output paths | Test command/results | Blocker |
|---|---|---|---|---|
| S06-T01 | Not started | — | — | — |
| S06-T02 | Not started | — | — | — |
| S06-T03 | Not started | — | — | — |
| S06-T04 | Not started | — | — | — |
| S06-T05 | Not started | — | — | — |
| S06-T06 | Not started | — | — | — |

## Source and artifact change record

| Consumed artifact | Revision or hash | Affected task(s) | Revalidation decision |
|---|---|---|---|
| TBD | TBD | TBD | TBD |

## Handoff

Update the registers with real paths and verification. The next step must read the latest output contracts, selected provider configurations and actual evidence. Any change to a prior artifact requires impact review and focused revalidation; the next step must not hard-code an old value copied from this document.
