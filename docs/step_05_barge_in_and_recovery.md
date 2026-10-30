# Step 05: Barge In And Recovery

**Status:** Complete (2026-10-30), except the 5 manual acoustic loopback runs (need a person and speakers).  
**Estimated engineering effort:** 28 hours.  
**Task owner:** Implementation agent; user confirms external paid credentials.  

## Purpose and scope

Deliver human-like interruptibility with correct cancellation and resilient fallbacks. Focus on ownership and evidence, not cosmetic product polish. Follow the global project non-goals in [master plan](./voicecore_lab_career_aligned_plan.md#explicit-non-goals).

## Step-specific implementation-agent prompt

> Act as a senior real-time voice software engineer. Read this step, the canonical [plan](./voicecore_lab_career_aligned_plan.md), [process](./README.md#source-of-truth-and-change-detection), and referenced previous step outputs. Inspect the existing code and prior execution records. Implement all remaining tasks in dependency order, verify with real commands and tests, record actual evidence/paths, and stop at this step's exit gate. Never invent pass results, provider support, latency numbers or source files.

## Required reading and prerequisites

- [Master architecture and contracts](./voicecore_lab_career_aligned_plan.md#system-architecture)
- [Previous step](./step_04_grounded_docs_agent.md) and its actual outputs, not merely planned files.
- Exact upstream code artifacts and ADRs named in the tasks below; if missing, record blocker and do independent preparations only.

## Decision ownership

This step owns the task-specific implementation choices, contracts and test evidence described below. It inherits the public goals, constraints, budget philosophy, evaluation thresholds and overall stack from the master plan. Do not silently change cross-step contracts. If needed, update the responsible upstream ADR/document and mark affected work for review.

## Phases and specific tasks

### S05-T01 — Barge-in detector

**Outcome / implementation:** Trigger interrupt while agent speaks using mic VAD and echo-aware gating; distinguish speech from loudspeaker echo.  
**Inputs:** This document, [master](./voicecore_lab_career_aligned_plan.md), current upstream records and working code.  
**Dependencies:** None beyond prerequisites.  
**Expected artifacts:** `services/agent-core/voicecore/turntaking (barge_in)` (planned; actual paths may be selected in owner register).  
**Edge/failure concerns:** Handle invalid input, task cancellation, empty data and path/session lifecycle where applicable; explicitly mark any scenario that is genuinely not applicable.  
**Acceptance test:** Interrupt triggers on synthetic speech but not echo-only reference cases.  

### S05-T02 — Generation cancellation

**Outcome / implementation:** Cancel LLM/TTS, invalidate stale generation, clear queued audio, stop output on client with ACK.  
**Inputs:** This document, [master](./voicecore_lab_career_aligned_plan.md), current upstream records and working code.  
**Dependencies:** S05-T01.  
**Expected artifacts:** `services/agent-core/voicecore/runtime, services/realtime-gateway/session (fence), packages/web-sdk/src/playout` (planned; actual paths may be selected in owner register).  
**Edge/failure concerns:** Handle invalid input, task cancellation, empty data and path/session lifecycle where applicable; explicitly mark any scenario that is genuinely not applicable.  
**Acceptance test:** Late TTS bytes and late tokens cannot resume a cancelled turn.  

### S05-T03 — Recovery paths

**Outcome / implementation:** Define STT timeout, TTS disconnect, provider 429, client pause, mic revocation, network loss.  
**Inputs:** This document, [master](./voicecore_lab_career_aligned_plan.md), current upstream records and working code.  
**Dependencies:** S05-T02.  
**Expected artifacts:** `services/agent-core/voicecore/runtime (recovery rules)` (planned; actual paths may be selected in owner register).  
**Edge/failure concerns:** Handle invalid input, task cancellation, empty data and path/session lifecycle where applicable; explicitly mark any scenario that is genuinely not applicable.  
**Acceptance test:** User gets deterministic recoverable state; reconnected session does not duplicate speech.  

### S05-T04 — Interruption benchmark

**Outcome / implementation:** Measure interrupt-to-silence, interrupt-to-listening and false barge-in on 20+ staged scripts.  
**Inputs:** This document, [master](./voicecore_lab_career_aligned_plan.md), current upstream records and working code.  
**Dependencies:** S05-T03.  
**Expected artifacts:** `reports/barge_in.md` (planned; actual paths may be selected in owner register).  
**Edge/failure concerns:** Handle invalid input, task cancellation, empty data and path/session lifecycle where applicable; explicitly mark any scenario that is genuinely not applicable.  
**Acceptance test:** Timestamps and clips back each calculated percentile; all pass/fails explicit.  

### S05-T05 — Chaos controls

**Outcome / implementation:** Add deterministic latency, packet loss, provider stalls, failure injections via config, not monkeypatching.  
**Inputs:** This document, [master](./voicecore_lab_career_aligned_plan.md), current upstream records and working code.  
**Dependencies:** S05-T04.  
**Expected artifacts:** `harness/scenarios/chaos` (planned; actual paths may be selected in owner register).  
**Edge/failure concerns:** Handle invalid input, task cancellation, empty data and path/session lifecycle where applicable; explicitly mark any scenario that is genuinely not applicable.  
**Acceptance test:** CI runs injection scenarios with reproducible seeds.  

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
| Barge-in = floor `barge_in` (echo gate on while the client plays) → `Session.cancel`: fence, LLM task cancelled, `tts.cancel`, `agent.cancel` to gateway and client | S05-T01 | `runtime/session.py`, `turntaking/floor.py` | `harness/tests/test_barge_in.py` | Done |
| Cancellation is enforced at every queue owner: Python (`_alive` check at the TTS reader and before every send), gateway (`TestAgentFramesAtOrBelowFenceAreNotSent`, `TestResumeDropsAudioQueuedWhileAway`), browser (`Playout.cancel`, `client.test.ts`), Cartesia adapter (drop after cancel) | S05-T02 | as listed | tests listed | Done |
| Recovery rules: STT final 5 s after endpoint → reprompt; TTS failure → text answer, then one retry on a fresh TTS stream if nothing was heard yet; 429 before any text → backoff 1/2/4 s → "I'm busy"; client paused > 30 s → cancel; mic revoked → that stream ignored, text works, a new stream works; network loss → gateway resume + `client.resumed` cancel (S01-T04, S03-T02) | S05-T03 | `runtime/session.py`, `server.py` (TTS factory, credits summed across streams, one shared 1,500-character cap) | `test_recovery.py` (7) | Done |
| Chaos: JSON fault schedule + seed builds the mocks; one in-process run on fake time; traces compared after making times relative | S05-T05 | `harness/runner/chaos.py`, `harness/scenarios/chaos/stall_and_429.json` | `harness/tests/test_chaos.py` | Done |
| Live barge-in harness: headless client asks by text, mixes its own playback into its mic (−15 dB, ~40 ms) and starts a user clip 1.2 s into playback; renders by the wall clock (fixed after false barge-ins) | S05-T04 | `packages/web-sdk/bin/headless-client.ts`, `harness/barge_live.py` | `reports/barge_in.md` | Done |
| During playback, STT opens only when the user holds the floor (echo transcripts leaked into the next turn, found live) | S05-T04 | `Session._to_stt` | `test_echo_of_the_agent_is_not_sent_to_stt_while_it_plays` | Done |

## Execution record

| Task ID | Status | Output paths | Test command/results | Blocker |
|---|---|---|---|---|
| S05-T01 | Done 2026-10-30 | `harness/runner/inprocess.py::run_barge_in`, `harness/tests/test_barge_in.py` | 3 dev interrupt clips: `agent.cancel{gen:1}`, client `playout.stopped{cancel}`, interrupt-to-silence ≤ 500 ms; 2 dev echo-only clips: no barge-in, answer plays to the end (real Silero, fake time) | — |
| S05-T02 | Done 2026-10-30 | `packages/web-sdk/src/client.test.ts` (+ earlier gateway and runtime tests) | client: agent frame → playout.push, `agent.cancel` → playout.cancel before the app callback; reconnect resumes with the learned session id | — |
| S05-T03 | Done 2026-10-30 | `voicecore/runtime/session.py` | `test_recovery.py` → 7 passed: reprompt at 5 s (not 4.5); TTS drop → text + 1 retry spoken; 429 calls at 0/1/3/7 s then BUSY; 429 then success answers; pause 31 s cancels, resume at 20 s keeps; revoked mic ignored, text answers | No STT reconnect (ponytail note) |
| S05-T04 | Done 2026-10-30 (fake + live); manual open | `reports/barge_in.md`, `reports/barge_in_fake.json`, `benchmarks/raw/barge_live_*` | Fake 24 scripts: 20/20 silenced, p50 180 ms at 0 ms one-way delay → 380 ms at 100 ms; 0/4 false. Live after fixes: 8/8 silenced, p50 303 / p95 1,364 ms; 0/4 false (4/4 before the render fix) | 5 manual acoustic runs need the user |
| S05-T05 | Done 2026-10-30 | `harness/runner/chaos.py`, `harness/scenarios/chaos/stall_and_429.json` | seed 42: identical normalized trace and client log twice; 429 backoff and 8 s stall both present; one reprompted answer | — |

## Source and artifact change record

| Consumed artifact | Revision or hash | Affected task(s) | Revalidation decision |
|---|---|---|---|
| Code review (medium, `a3f2d10..2bbb93a`, Steps 04–05): 10 findings, all fixed: async TTS errors after the text was sent got no retry and stranded the turn; pause timer leaked across generations and past close; a refusal after a grounded sentence mislabelled the answer; mic revoke mid-utterance stranded the turn; echo tail (200 ms) still reached STT; fatal TTS cap was retried; `max([])` and falsy-zero onset in the harness; retrieval blocked the event loop (now `asyncio.to_thread`, sqlite lock); stale partial audio prepended to a retry | review 2026-10-30 | S04-T03, S05-T03, S05-T04 | 4 regression tests added |
| `fixtures/audio` interrupt/echo clips | manifest rebuilt 2026-10-30 (−23 dBFS) | S05-T01, T04 | consumed |
| `docs/adr/0002-turn-policy.md` echo gate parameters | 2026-10-30 | S05-T01, T04 | unchanged; short-first-word weakness recorded |

## Handoff

Update the registers with real paths and verification. The next step must read the latest output contracts, selected provider configurations and actual evidence. Any change to a prior artifact requires impact review and focused revalidation; the next step must not hard-code an old value copied from this document.
