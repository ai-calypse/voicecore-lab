# Step 03: Streaming Orchestrator

**Status:** Planned; no implementation or test evidence yet.  
**Estimated engineering effort:** 38 hours.  
**Task owner:** Implementation agent; user confirms external paid credentials.  

## Purpose and scope

Own the speech-to-speech pipeline, cancellation semantics, and cross-provider adapters. Focus on ownership and evidence, not cosmetic product polish. Follow the global project non-goals in [master plan](./voicecore_lab_career_aligned_plan.md#explicit-non-goals).

## Step-specific implementation-agent prompt

> Act as a senior real-time voice software engineer. Read this step, the canonical [plan](./voicecore_lab_career_aligned_plan.md), [process](./README.md#source-of-truth-and-change-detection), and referenced previous step outputs. Inspect the existing code and prior execution records. Implement all remaining tasks in dependency order, verify with real commands and tests, record actual evidence/paths, and stop at this step's exit gate. Never invent pass results, provider support, latency numbers or source files.

## Provider baseline to honor

Before implementing this step, read the canonical [initial voice-model provider decisions](./voicecore_lab_career_aligned_plan.md#initial-voice-model-providers-default-integrations-not-hard-vendor-lock-in). Do not invent specific SDK methods, freeze unknown model IDs, claim that a provider was integrated, or bypass the replaceable adapter design. Verify current official streaming contracts and record selected model/API revisions in this step's decision register before any live provider usage.

## Required reading and prerequisites

- [Master architecture and contracts](./voicecore_lab_career_aligned_plan.md#system-architecture)
- [Previous step](./step_02_voice_activity_and_turn_detection.md) and its actual outputs, not merely planned files.
- Exact upstream code artifacts and ADRs named in the tasks below; if missing, record blocker and do independent preparations only.

## Decision ownership

This step owns the task-specific implementation choices, contracts and test evidence described below. It inherits the public goals, constraints, budget philosophy, evaluation thresholds and overall stack from the master plan. Do not silently change cross-step contracts. If needed, update the responsible upstream ADR/document and mark affected work for review.

## Phases and specific tasks

### S03-T01 — Provider contracts

**Outcome / implementation:** Write typed streaming STT, LLM and TTS adapters; support mock and >=1 live provider in each category.  
**Inputs:** This document, [master](./voicecore_lab_career_aligned_plan.md), current upstream records and working code.  
**Dependencies:** None beyond prerequisites.  
**Expected artifacts:** `services/agent-core/voicecore/providers and services/agent-core/tests/provider_contract` (planned; actual paths may be selected in owner register).  
**Edge/failure concerns:** Handle invalid input, task cancellation, empty data and path/session lifecycle where applicable; explicitly mark any scenario that is genuinely not applicable.  
**Acceptance test:** Offline mocks and live smoke tests use one interface, errors carry retry classification.  

### S03-T02 — Session/turn state machine

**Outcome / implementation:** Model listen, speech, partial transcript, retrieval, generation, synth, playback and termination with generation IDs.  
**Inputs:** This document, [master](./voicecore_lab_career_aligned_plan.md), current upstream records and working code.  
**Dependencies:** S03-T01.  
**Expected artifacts:** `services/agent-core/voicecore/runtime` (planned; actual paths may be selected in owner register).  
**Edge/failure concerns:** Handle invalid input, task cancellation, empty data and path/session lifecycle where applicable; explicitly mark any scenario that is genuinely not applicable.  
**Acceptance test:** Property/state tests reject illegal transitions and stale results.  

### S03-T03 — Incremental STT and LLM

**Outcome / implementation:** Consume interim/final hypotheses correctly, stream answer tokens, isolate upstream blocking and cancellation.  
**Inputs:** This document, [master](./voicecore_lab_career_aligned_plan.md), current upstream records and working code.  
**Dependencies:** S03-T02.  
**Expected artifacts:** `services/agent-core/voicecore/runtime (transcript assembler)` (planned; actual paths may be selected in owner register).  
**Edge/failure concerns:** Handle invalid input, task cancellation, empty data and path/session lifecycle where applicable; explicitly mark any scenario that is genuinely not applicable.  
**Acceptance test:** No duplicate text when interim hypotheses revise; stalled model times out.  

### S03-T04 — Chunked TTS pipeline

**Outcome / implementation:** Split at sentence/prosody boundaries, pipeline synthesis, sequence and play chunks in order.  
**Inputs:** This document, [master](./voicecore_lab_career_aligned_plan.md), current upstream records and working code.  
**Dependencies:** S03-T03.  
**Expected artifacts:** `services/agent-core/voicecore/runtime (TTS chunker, outbound sequencer)` (planned; actual paths may be selected in owner register).  
**Edge/failure concerns:** Handle invalid input, task cancellation, empty data and path/session lifecycle where applicable; explicitly mark any scenario that is genuinely not applicable.  
**Acceptance test:** No chunk reordering; audio start measured; no reading sources as raw URL strings.  

### S03-T05 — Streaming concurrency tests

**Outcome / implementation:** Simulate 20 simultaneous fake users and randomized provider delays/errors using deterministic clock.  
**Inputs:** This document, [master](./voicecore_lab_career_aligned_plan.md), current upstream records and working code.  
**Dependencies:** S03-T04.  
**Expected artifacts:** `harness/runner (in-process concurrency scenario)` (planned; actual paths may be selected in owner register).  
**Edge/failure concerns:** Handle invalid input, task cancellation, empty data and path/session lifecycle where applicable; explicitly mark any scenario that is genuinely not applicable.  
**Acceptance test:** No lost turn IDs, deadlocks, orphan streams or unbounded queues.  

### S03-T06 — Latency breakdown

**Outcome / implementation:** Instrument VAD, STT, retrieval, LLM TTFT, TTS first chunk and playback start with event spans.  
**Inputs:** This document, [master](./voicecore_lab_career_aligned_plan.md), current upstream records and working code.  
**Dependencies:** S03-T05.  
**Expected artifacts:** `reports/latency_breakdown.md` (planned; actual paths may be selected in owner register).  
**Edge/failure concerns:** Handle invalid input, task cancellation, empty data and path/session lifecycle where applicable; explicitly mark any scenario that is genuinely not applicable.  
**Acceptance test:** Spans separate client and server monotonic times and label assumptions.  

**Order inside this step** (decision 2026-10-29, see [build plan](./IMPLEMENTATION_PLAN.md)): T01 → T02 → T03 → T04 → T07 → T05 → T06. T02–T05 are tested at one seam, the generation runtime.

### S03-T07 — Wire-up and runner (new)

**Outcome / implementation:** Gateway hop server in Python, runtime uses the turn-taking module, harness runner gets an in-process adapter (fake time) and a WSS adapter driving headless clients with real-time pacing.  
**Inputs:** This document, [master](./voicecore_lab_career_aligned_plan.md), current upstream records and working code.  
**Dependencies:** S03-T04.  
**Expected artifacts:** `services/agent-core/voicecore/server.py, harness/runner, packages/web-sdk/bin/headless-client.ts` (planned; actual paths may be selected in owner register).  
**Edge/failure concerns:** Handle invalid input, task cancellation, empty data and path/session lifecycle where applicable; explicitly mark any scenario that is genuinely not applicable.  
**Acceptance test:** In-process run of a single-speaker fixture produces an endpoint, generation 1 and mock audio; a WSS run through gateway and Python logs `playout.started` and every span.  

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
| S03-T01 | Not started | — | — | — |
| S03-T02 | Not started | — | — | — |
| S03-T03 | Not started | — | — | — |
| S03-T04 | Not started | — | — | — |
| S03-T05 | Not started | — | — | — |
| S03-T06 | Not started | — | — | — |
| S03-T07 | Not started | — | — | — |

## Source and artifact change record

| Consumed artifact | Revision or hash | Affected task(s) | Revalidation decision |
|---|---|---|---|
| TBD | TBD | TBD | TBD |

## Handoff

Update the registers with real paths and verification. The next step must read the latest output contracts, selected provider configurations and actual evidence. Any change to a prior artifact requires impact review and focused revalidation; the next step must not hard-code an old value copied from this document.
