# Step 01: Audio Transport And Sdk

**Status:** Complete (2026-10-30). All 7 tasks done with fake-provider evidence; shaped-network loss profile waits on the user (needs sudo).  
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
**Expected artifacts:** `packages/web-sdk/src/capture` (planned; actual paths may be selected in owner register).  
**Edge/failure concerns:** Handle invalid input, task cancellation, empty data and path/session lifecycle where applicable; explicitly mark any scenario that is genuinely not applicable.  
**Acceptance test:** Tests verify sample rates, endian, silence/clip safety, frame ordering, no audio before consent.  

### S01-T02 — Custom binary transport

**Outcome / implementation:** Implement secure WebSocket media transport in Go; versioned header seq/timestamp/stream ID; decode, routing, heartbeat and close.  
**Inputs:** This document, [master](./voicecore_lab_career_aligned_plan.md), current upstream records and working code.  
**Dependencies:** S01-T01.  
**Expected artifacts:** `packages/protocol (SPEC.md, vectors) and services/realtime-gateway/{protocol,session}` (planned; actual paths may be selected in owner register).  
**Edge/failure concerns:** Handle invalid input, task cancellation, empty data and path/session lifecycle where applicable; explicitly mark any scenario that is genuinely not applicable.  
**Acceptance test:** Contract tests for partial frame, invalid header, replay/duplicate, stale packet, close.  

### S01-T03 — Backpressure and counters

**Outcome / implementation:** Implement bounded queues with a drop-oldest overload policy, sequence-gap detection across resume, and duplicate/stale drops; expose queue depth, drops and gaps. No reorder buffer: one WebSocket runs over TCP, so frames cannot arrive out of order; the reorder/seq-wrap jitter buffer moved to S07-T01 (decision 2026-10-29, see [build plan](./IMPLEMENTATION_PLAN.md)).  
**Inputs:** This document, [master](./voicecore_lab_career_aligned_plan.md), current upstream records and working code.  
**Dependencies:** S01-T02.  
**Expected artifacts:** `services/realtime-gateway/session (bounded queues, counters)` (planned; actual paths may be selected in owner register).  
**Edge/failure concerns:** Handle invalid input, task cancellation, empty data and path/session lifecycle where applicable; explicitly mark any scenario that is genuinely not applicable.  
**Acceptance test:** Injected saturation stays bounded and is counted; duplicate, stale and gap counters are exposed and correct.  

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

**Order inside this step** (decision 2026-10-29, see [build plan](./IMPLEMENTATION_PLAN.md)): S01-T02 protocol slices → S01-T01 → rest of S01-T02 → S01-T03 → S01-T04 → S01-T06 → S01-T07 → S01-T05.

### S01-T06 — Ordered playout (new)

**Outcome / implementation:** Browser playout module: generation-tagged frames, time-based underrun fill, cancel/fence flush, `playout.started/stopped` and `cancel.ack` events, pause/resume.  
**Inputs:** This document, [master](./voicecore_lab_career_aligned_plan.md), current upstream records and working code.  
**Dependencies:** S01-T02.  
**Expected artifacts:** `packages/web-sdk/src/playout` (planned; actual paths may be selected in owner register).  
**Edge/failure concerns:** Handle invalid input, task cancellation, empty data and path/session lifecycle where applicable; explicitly mark any scenario that is genuinely not applicable.  
**Acceptance test:** Offline-adapter tests show no sample of a fenced generation is rendered after cancel, and each playout event carries generation and time.  

### S01-T07 — Browser-to-gateway tracer bullet (new)

**Outcome / implementation:** Fake-mic audio from a browser page round-trips through the Go gateway and a scripted fake orchestrator and is played out.  
**Inputs:** This document, [master](./voicecore_lab_career_aligned_plan.md), current upstream records and working code.  
**Dependencies:** S01-T04, S01-T06.  
**Expected artifacts:** `services/realtime-gateway/cmd/fakeorch and a Playwright e2e test` (planned; actual paths may be selected in owner register).  
**Edge/failure concerns:** Handle invalid input, task cancellation, empty data and path/session lifecycle where applicable; explicitly mark any scenario that is genuinely not applicable.  
**Acceptance test:** Playwright test is green in CI and the page emits `playout.started`.  

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
| Wire protocol v1: 28-byte big-endian header (version, kind, flags, stream_id, sequence, capture_us u64, generation_id, samples, reserved), PCM16 LE payload; JSON control events with a required-field table; close codes 1007/1008/4001/4002/4003; generation fencing rule; trace event schema | S01-T02 | `packages/protocol/SPEC.md`, `packages/protocol/vectors/` | golden vectors pass in TS, Go, Python | Done |
| One codec per language, each tested against the same vectors (8 valid + 5 invalid frames, 21 valid + 5 invalid events) | S01-T02 | `packages/protocol/ts/`, `services/realtime-gateway/protocol/`, `services/agent-core/voicecore/protocol.py` | `frame.test.ts`, `events.test.ts`, `TestGoldenFrames`, `TestGoldenEvents`, `test_protocol.py` | Done |
| Capture: AudioContext at device rate + own windowed-sinc resampler (64 taps, 7 kHz cutoff) to 16 kHz, clamp/round PCM16 rule, 320-sample framer; capture_us derived from the sample count so frames are exactly 20 ms apart | S01-T01 | `packages/web-sdk/src/capture/` | `capture.test.ts` (5), Playwright `capture.spec.ts` | Done |
| Worklets are injected from source strings (capture) and `Playout.toString()` (playout), so the SDK needs no bundler step for worklet files | S01-T01, S01-T06 | `capture/index.ts`, `playout/worklet-adapter.ts` | tracer bullet plays audio in Chromium | Done |
| Gateway: coder/websocket v1.8.14, HMAC dev token (60 s), hello within 5 s, ping/pong, 10 s heartbeat, 10 s resume window keeping the upstream socket, per-stream duplicate/stale/gap rules, drop-oldest mic queue (50), outbound queue (1,500) with fence purge on `agent.cancel`, `/debug/counters` | S01-T02..T04 | `services/realtime-gateway/session/` | 20 synctest tests + goleak, `-race` | Done |
| Tests run inside `testing/synctest` over `internal/memnet` (net.Pipe), so heartbeat and resume timing are exact in fake time | S01-T02..T04 | `internal/memnet/`, `session/rig_test.go` | 30 consecutive runs without failure; 4 deliberate mutations each caught | Done |
| Playout: pull-model `Playout` (render per block), fence on cancel, time-based underrun, `playout.started/stopped`, `cancel.ack{played_until_seq}`, pause/resume; worklet adapter converts audio-clock times to the page clock with `getOutputTimestamp()` | S01-T06 | `packages/web-sdk/src/playout/` | `playout.test.ts` (6) | Done |
| No sudo for the agent: shaped-network numbers use a userspace delay/jitter proxy (`simulated`, no loss); dummynet commands written for the user | S01-T05 | `cmd/wsload`, `benchmarks/README.md` | `benchmarks/transport.md` | Loss profile waiting on user |

## Execution record

| Task ID | Status | Output paths | Test command/results | Blocker |
|---|---|---|---|---|
| S01-T01 | Done 2026-10-29 | `packages/web-sdk/src/capture/`, `src/client.ts`, `apps/demo/e2e/capture.spec.ts` | `pnpm --filter @voicecore/web-sdk test` → 5 capture tests pass (1 kHz zero crossings, 48k/44.1k counts in 128-sample chunks, 9 kHz attenuated ≥ 20 dB, PCM rule, framer). Playwright (Chromium, fake mic file `dev/single_01.wav`): 0 binary frames before `startMic()`, then 320-sample kind-1 frames, contiguous sequence, capture_us step exactly 20,000 us, speech peak > 1000 | — |
| S01-T02 | Done 2026-10-29 | `packages/protocol/`, `services/realtime-gateway/{protocol,session,internal,cmd}` | Golden vectors pass in vitest, `go test`, pytest. `FuzzDecodeFrame` 20 s locally (7.4 M execs, no crash; 30 s in CI). Session: valid hello → welcome; invalid header and truncated frame → 1007; non-hello first → 1008; duplicate and stale counted; 10 frames forwarded in order; heartbeat close at exactly 10 s; clean close releases the session | Fuzz name is `FuzzDecodeFrame` (Go requires the `Fuzz` prefix), not `TestFrameFuzzNeverPanics` |
| S01-T03 | Done 2026-10-29 | `session/session.go` (`queue`, `acceptMic`) | 100 frames into a stalled upstream: `drops_overload` 49, depth 50, upstream later receives 0 and 50–99. Counters JSON exact. Gap after resume = 3 | — |
| S01-T04 | Done 2026-10-29 | `session/` | Expired and forged tokens → 4001; 48 kHz hello → 4002; resume at 9 s keeps the session and sends `client.resumed` upstream without a second upstream socket; resume at 11 s starts a new session; mic revoke drops later frames of that stream, keeps text and new streams; fence: 4 queued + 1 late gen-1 frames dropped, gen 2 delivered; no goroutines left after stop/expire/resume (`go test -race`, goleak) | — |
| S01-T05 | Done 2026-10-30 (local + simulated) | `services/realtime-gateway/cmd/wsload`, `benchmarks/transport.md`, `benchmarks/raw/transport_20261030T003218Z.jsonl` | Gateway adds 0.19 ms median RTT (two passes, 1 stream); 20 streams RTT p50/p95/p99 1.08/1.68/2.16 ms; 0 drops, 0 gaps; decode 205.7 ns + 1 alloc per frame | Real loss profile needs `sudo` (user) |
| S01-T06 | Done 2026-10-29 | `packages/web-sdk/src/playout/` | 6 offline-adapter tests: started time, 100 ms underrun, cancel flush + ack, cancel before start, gen 2 after cancel, pause/resume | — |
| S01-T07 | Done 2026-10-29 | `cmd/fakeorch`, `apps/demo/e2e/tracer.spec.ts`, CI `e2e` job | Playwright: page → gateway → fakeorch echo → page playout emits `playout.started{gen:1}`; gateway counters show 0 drops | — |

## Source and artifact change record

| Consumed artifact | Revision or hash | Affected task(s) | Revalidation decision |
|---|---|---|---|
| `docs/IMPLEMENTATION_PLAN.md` Step 01 | as of `317bf09` | all | Followed; deviations recorded above |
| `fixtures/audio/dev/single_01.wav` | sha256 in `fixtures/audio/manifest.json` | S01-T01 | fake mic input |
| coder/websocket docs (Context7 `/coder/websocket`, v1.8.12 docs; module v1.8.14) | fetched 2026-10-29 | S01-T02..T04 | `CloseStatus`, `CloseRead`, `Dial` with `HTTPClient` |

## Handoff

Update the registers with real paths and verification. The next step must read the latest output contracts, selected provider configurations and actual evidence. Any change to a prior artifact requires impact review and focused revalidation; the next step must not hard-code an old value copied from this document.
