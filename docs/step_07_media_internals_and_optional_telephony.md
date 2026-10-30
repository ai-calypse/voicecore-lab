# Step 07: Media Internals And Optional Telephony

**Status:** Complete within the timebox (2026-10-30), except the shaped-network (dummynet) WS vs WebRTC run, which needs `sudo` (user). Telephony is a design document only, with no SIP claim.  
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

**Outcome / implementation:** Implement RTP packet inspect/reorder/seq-wrap and RTCP jitter interpretation on fixtures or loopback, plus the reorder/seq-wrap jitter buffer moved here from S01-T03 (decision 2026-10-29, see [build plan](./IMPLEMENTATION_PLAN.md)).  
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
| Jitter buffer = fixed playout delay from first arrival (`first + delay + 20 ms × n`); late = arrived after its play time (dropped); lost = play time without a packet, only up to the highest sequence seen; 16-bit sequence unwrapped against the highest seen | S07-T01 | `experiments/rtp/jitter.go` | `jitter_test.go` | Done |
| RFC 3550 §6.4.1 interarrival jitter `J += (|D| − J)/16` in clock units | S07-T01 | `experiments/rtp/jitter.go::Jitter` | hand-worked 4-packet value 3.59619140625 | Done |
| Spike: Pion WebRTC v4.2.26, non-trickle (wait for ICE gathering), loopback only (no STUN/TURN), browser offers, Go answers; every Opus RTP packet goes into the T01 buffer and RFC 3550 jitter; ICE / DTLS / connection steps logged. The DTLS handler must be attached when the offer creates the transceiver (inside `OnTrack` it missed the handshake) | S07-T02 | `experiments/cmd/pion-peer/` | Playwright `webrtc.spec.ts` | Done |
| Comparison timed in one process: Pion receives WebRTC and also speaks the VoiceCore WS protocol on `/ws` | S07-T03 | `pion-peer` `/ws`, `webrtc.spec.ts` (BENCH=1) | `benchmarks/raw/webrtc_vs_ws_20261030T024016Z.json` | Done (local); shaped runs need sudo |
| Telephony: Twilio Media Streams adapter design in front of the unchanged gateway; SIP flow written down; no code | S07-T04 | `docs/telephony_extension.md` | — | Done (design only) |
| Experiments are a separate Go module (`experiments/`, replace → gateway module for the protocol codec); CI `go` job runs its tests | S07 | `experiments/go.mod`, `.github/workflows/ci.yml` | CI | Done |

## Execution record

| Task ID | Status | Output paths | Test command/results | Blocker |
|---|---|---|---|---|
| S07-T01 | Done 2026-10-30 | `experiments/rtp/` | `go test -race ./...` → 4 passed: 65534, 0, 65535, 1 come out 65534, 65535, 0, 1; RFC 3550 jitter literal; reordered within the window in order, late dropped and counted, missing counted lost; duplicate counted | — |
| S07-T02 | Done 2026-10-30 | `experiments/cmd/pion-peer/main.go`, `index.html`, `apps/demo/e2e/webrtc.spec.ts` | Playwright (Chromium fake mic): steps offer applied → ice checking → answer sent → ice connected → dtls connected → connection connected; codec audio/opus; > 100 packets through the jitter buffer; interarrival p50 between 15 and 25 ms | — |
| S07-T03 | Done 2026-10-30 (loopback only) | `docs/media_internals.md`, `benchmarks/raw/webrtc_vs_ws_20261030T024016Z.json` | WebRTC 1,002 packets, interarrival p50/p95 20.06/20.41 ms, jitter 0.26 ms; WS 500 frames, 19.86/29.53 ms, jitter 4.84 ms; 0 late, 0 lost on both. Burstiness comes from the SDK's worklet → main-thread framing | Shaped (dummynet) profiles need sudo (user) |
| S07-T04 | Done 2026-10-30 (design) | `docs/telephony_extension.md` | SIP call flow; Media Streams adapter table (μ-law, 8↔16/24 kHz, `clear` on `agent.cancel`, `mark` → playout events); tests it would need listed | Not built: no SIP claim |
| S07-T05 | Done 2026-10-30 | `docs/media_internals.md` | links code, tests and every measured number with its source | — |

## Source and artifact change record

| Consumed artifact | Revision or hash | Affected task(s) | Revalidation decision |
|---|---|---|---|
| `benchmarks/transport.md` | 2026-10-30 | S07-T03, T05 | simulated proxy results reused to explain TCP jitter |
| Pion WebRTC docs (Context7 `/pion/webrtc`) | fetched 2026-10-30 | S07-T02 | `OnTrack`/`ReadRTP`, `GatheringCompletePromise` |

## Handoff

Update the registers with real paths and verification. The next step must read the latest output contracts, selected provider configurations and actual evidence. Any change to a prior artifact requires impact review and focused revalidation; the next step must not hard-code an old value copied from this document.
