# Step 07: Media Internals And Optional Telephony

**Status:** Planned; no implementation or test evidence yet.  
**Estimated engineering effort:** 35 hours.  
**Task owner:** Implementation agent; user confirms external paid credentials.  

## Purpose and scope

Deepen networking knowledge with an independent WebRTC/telephony systems experiment. Focus on ownership and evidence, not cosmetic product polish. Follow the global project non-goals in [master plan](./voicecore_lab_career_aligned_plan.md#explicit-non-goals).

## Step-specific implementation-agent prompt

> Act as a senior real-time voice software engineer. Read this step, the canonical [plan](./voicecore_lab_career_aligned_plan.md), [process](./README.md#source-of-truth-and-change-detection), and referenced previous step outputs. Inspect the existing code and prior execution records. Implement all remaining tasks in dependency order, verify with real commands and tests, record actual evidence/paths, and stop at this step's exit gate. Never invent pass results, provider support, latency numbers or source files.

## Required reading and prerequisites

- [Master architecture and contracts](./voicecore_lab_career_aligned_plan.md#system-architecture)
- [Previous step](./step_06_observability_evals_and_load.md) and its actual outputs, not merely planned files.
- Exact upstream code artifacts and ADRs named in the tasks below; if missing, record blocker and do independent preparations only.

## Decision ownership

This step owns the task-specific implementation choices, contracts and test evidence described below. It inherits the public goals, constraints, budget philosophy, evaluation thresholds and overall stack from the master plan. Do not silently change cross-step contracts. If needed, update the responsible upstream ADR/document and mark affected work for review.

## Phases and specific tasks

### S07-T01 — RTP/RTCP technical lab

**Outcome / implementation:** Implement RTP packet inspect/reorder/seq-wrap and RTCP jitter interpretation on fixtures or loopback.  
**Inputs:** This document, [master](./voicecore_lab_career_aligned_plan.md), current upstream records and working code.  
**Dependencies:** None beyond prerequisites.  
**Expected artifacts:** `experiments/rtp_lab/` (planned; actual paths may be selected in owner register).  
**Edge/failure concerns:** Handle invalid input, task cancellation, empty data and path/session lifecycle where applicable; explicitly mark any scenario that is genuinely not applicable.  
**Acceptance test:** Source and tests show exact packet arithmetic, loss/jitter calculations.  

### S07-T02 — WebRTC Pion spike

**Outcome / implementation:** Establish peer connection over Pion with browser (ICE, SDP, DTLS-SRTP); receive track and inspect Opus/RTP.  
**Inputs:** This document, [master](./voicecore_lab_career_aligned_plan.md), current upstream records and working code.  
**Dependencies:** S07-T01.  
**Expected artifacts:** `experiments/webrtc_pion/` (planned; actual paths may be selected in owner register).  
**Edge/failure concerns:** Handle invalid input, task cancellation, empty data and path/session lifecycle where applicable; explicitly mark any scenario that is genuinely not applicable.  
**Acceptance test:** Recorded negotiation steps; errors at NAT/candidate stages documented.  

### S07-T03 — Transport comparison

**Outcome / implementation:** Compare custom WS PCM vs WebRTC under injected jitter and packet loss; clearly control codec and signal processing confounds.  
**Inputs:** This document, [master](./voicecore_lab_career_aligned_plan.md), current upstream records and working code.  
**Dependencies:** S07-T02.  
**Expected artifacts:** `reports/transport_comparison.md` (planned; actual paths may be selected in owner register).  
**Edge/failure concerns:** Handle invalid input, task cancellation, empty data and path/session lifecycle where applicable; explicitly mark any scenario that is genuinely not applicable.  
**Acceptance test:** Measured vs hypothetical performance labeled; reproducibility documented.  

### S07-T04 — Telephony protocol review

**Outcome / implementation:** Build minimal SIP call-flow state diagram and Twilio Media Streams or SIP/RTP adapter design, implementation conditional on budget.  
**Inputs:** This document, [master](./voicecore_lab_career_aligned_plan.md), current upstream records and working code.  
**Dependencies:** S07-T03.  
**Expected artifacts:** `docs/telephony_extension.md` (planned; actual paths may be selected in owner register).  
**Edge/failure concerns:** Handle invalid input, task cancellation, empty data and path/session lifecycle where applicable; explicitly mark any scenario that is genuinely not applicable.  
**Acceptance test:** Real integrations optional; never claim SIP support if only diagrams exist.  

### S07-T05 — Systems write-up

**Outcome / implementation:** Explain ICE/STUN/TURN, AEC, Opus, RTP/RTCP, media/server clocks and chosen tradeoffs.  
**Inputs:** This document, [master](./voicecore_lab_career_aligned_plan.md), current upstream records and working code.  
**Dependencies:** S07-T04.  
**Expected artifacts:** `docs/media_internals.md` (planned; actual paths may be selected in owner register).  
**Edge/failure concerns:** Handle invalid input, task cancellation, empty data and path/session lifecycle where applicable; explicitly mark any scenario that is genuinely not applicable.  
**Acceptance test:** Readme links to working code, packet captures and measured observations.  

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
| S07-T01 | Not started | — | — | — |
| S07-T02 | Not started | — | — | — |
| S07-T03 | Not started | — | — | — |
| S07-T04 | Not started | — | — | — |
| S07-T05 | Not started | — | — | — |

## Source and artifact change record

| Consumed artifact | Revision or hash | Affected task(s) | Revalidation decision |
|---|---|---|---|
| TBD | TBD | TBD | TBD |

## Handoff

Update the registers with real paths and verification. The next step must read the latest output contracts, selected provider configurations and actual evidence. Any change to a prior artifact requires impact review and focused revalidation; the next step must not hard-code an old value copied from this document.
