# Step 01: Audio Transport And Sdk

**Status:** Planned; no implementation or test evidence yet.  
**Estimated engineering effort:** 30 hours.  
**Task owner:** Implementation agent; user confirms external paid credentials.  

## Purpose and scope

Write the streaming microphone-to-server audio path with a real wire protocol and developer-friendly browser client. Focus on ownership and evidence, not cosmetic product polish. Follow the global project non-goals in [master plan](./voicecore_lab_career_aligned_plan.md#explicit-non-goals).

## Step-specific implementation-agent prompt

> Act as a senior real-time voice software engineer. Read this step, the canonical [plan](./voicecore_lab_career_aligned_plan.md), [process](./README.md#source-of-truth-and-change-detection), and referenced previous step outputs. Inspect the existing code and prior execution records. Implement all remaining tasks in dependency order, verify with real commands and tests, record actual evidence/paths, and stop at this step's exit gate. Never invent pass results, provider support, latency numbers or source files.

## Required reading and prerequisites

- [Master architecture and contracts](./voicecore_lab_career_aligned_plan.md#system-architecture)
- [Previous step](./step_00_career_evidence_and_baselines.md) and its actual outputs, not merely planned files.
- Exact upstream code artifacts and ADRs named in the tasks below; if missing, record blocker and do independent preparations only.

## Decision ownership

This step owns the task-specific implementation choices, contracts and test evidence described below. It inherits the public goals, constraints, budget philosophy, evaluation thresholds and overall stack from the master plan. Do not silently change cross-step contracts. If needed, update the responsible upstream ADR/document and mark affected work for review.

## Phases and specific tasks

### S01-T01 — Browser PCM capture

**Outcome / implementation:** Use AudioWorklet with microphone consent, mono PCM conversion, deterministic resampling to 16 kHz, and fixed 20-40 ms frames.  
**Inputs:** This document, [master](./voicecore_lab_career_aligned_plan.md), current upstream records and working code.  
**Dependencies:** None beyond prerequisites.  
**Expected artifacts:** `packages/web-sdk/src/audio and fixtures/audio/frame-tests` (planned; actual paths may be selected in owner register).  
**Edge/failure concerns:** Handle invalid input, task cancellation, empty data and path/session lifecycle where applicable; explicitly mark any scenario that is genuinely not applicable.  
**Acceptance test:** Tests verify sample rates, endian, silence/clip safety, frame ordering, no audio before consent.  

### S01-T02 — Custom binary transport

**Outcome / implementation:** Implement secure WebSocket media transport in Go; versioned header seq/timestamp/stream ID; decode, routing, heartbeat and close.  
**Inputs:** This document, [master](./voicecore_lab_career_aligned_plan.md), current upstream records and working code.  
**Dependencies:** S01-T01.  
**Expected artifacts:** `services/realtime-gateway/ws and packages/protocol` (planned; actual paths may be selected in owner register).  
**Edge/failure concerns:** Handle invalid input, task cancellation, empty data and path/session lifecycle where applicable; explicitly mark any scenario that is genuinely not applicable.  
**Acceptance test:** Contract tests for partial frame, invalid header, replay/duplicate, stale packet, close.  

### S01-T03 — Jitter and backpressure

**Outcome / implementation:** Implement bounded receive ring, sequence gaps, late frames, queues and overload policy; expose queue depth and drops.  
**Inputs:** This document, [master](./voicecore_lab_career_aligned_plan.md), current upstream records and working code.  
**Dependencies:** S01-T02.  
**Expected artifacts:** `services/realtime-gateway/buffer` (planned; actual paths may be selected in owner register).  
**Edge/failure concerns:** Handle invalid input, task cancellation, empty data and path/session lifecycle where applicable; explicitly mark any scenario that is genuinely not applicable.  
**Acceptance test:** Injected reorder/drop/saturation are bounded, stable and observable.  

### S01-T04 — Reconnect and lifecycle

**Outcome / implementation:** Implement session start/auth, negotiated format, resume behavior, expiry, end and mic revocation without leaked tasks.  
**Inputs:** This document, [master](./voicecore_lab_career_aligned_plan.md), current upstream records and working code.  
**Dependencies:** S01-T03.  
**Expected artifacts:** `services/realtime-gateway/session` (planned; actual paths may be selected in owner register).  
**Edge/failure concerns:** Handle invalid input, task cancellation, empty data and path/session lifecycle where applicable; explicitly mark any scenario that is genuinely not applicable.  
**Acceptance test:** No detached session goroutines after stop, expired token or reconnect in race tests.  

### S01-T05 — Raw transport benchmark

**Outcome / implementation:** Measure network upload cadence, processing overhead, per frame allocation, loss simulation against baseline.  
**Inputs:** This document, [master](./voicecore_lab_career_aligned_plan.md), current upstream records and working code.  
**Dependencies:** S01-T04.  
**Expected artifacts:** `benchmarks/transport.md` (planned; actual paths may be selected in owner register).  
**Edge/failure concerns:** Handle invalid input, task cancellation, empty data and path/session lifecycle where applicable; explicitly mark any scenario that is genuinely not applicable.  
**Acceptance test:** Local and shaped network evidence includes p50/p95 and test conditions.  

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
| S01-T01 | Not started | — | — | — |
| S01-T02 | Not started | — | — | — |
| S01-T03 | Not started | — | — | — |
| S01-T04 | Not started | — | — | — |
| S01-T05 | Not started | — | — | — |

## Source and artifact change record

| Consumed artifact | Revision or hash | Affected task(s) | Revalidation decision |
|---|---|---|---|
| TBD | TBD | TBD | TBD |

## Handoff

Update the registers with real paths and verification. The next step must read the latest output contracts, selected provider configurations and actual evidence. Any change to a prior artifact requires impact review and focused revalidation; the next step must not hard-code an old value copied from this document.
