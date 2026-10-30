# Step 03: Streaming Orchestrator

**Status:** Complete (2026-10-30). Live latency measured (n = 10); the Voice Agent `FAILED_TO_START_LISTENING` ticket is drafted for the user to send.  
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
| Before adapters: 10 back-to-back plain Deepgram listen sessions all succeeded (`benchmarks/raw/listen_repro_20261030T005307Z.json`, $0.0005), so the STT adapter does not share the Voice Agent's setup failure. Ticket with the 3 failed request IDs drafted for the user (`docs/support/deepgram_failed_to_start_listening.md`) | S03 prerequisite | `harness/listen_repro.py` | 10/10 ok | Done; ticket waits on user |
| Contracts: `STTStream` (send, finalize, events, close), `LLM.stream` (TextDelta, ToolCall, Done), `TTSStream` (synth per generation, audio, cancel, close); `ProviderError(retryable / rate_limited / fatal)` from HTTP status | S03-T01 | `voicecore/providers/base.py` | `test_provider_contracts.py` | Done |
| Mocks are scripts (delays, tokens, errors, stalls), also the fault injector; MockSTT is audio-time driven so runs are deterministic | S03-T01 | `providers/mock.py` | runtime and concurrency tests | Done |
| Live: Deepgram nova-3 (`Finalize` at our endpoint, `KeepAlive` every 4 s idle, keyterms `uv`, `uvx`, `uv sync`, `uv lock`, `pyproject.toml`; trailing interim promoted to final on close after one live run ended without a final); OpenRouter `openai/gpt-4.1-nano` with the official `openai` SDK 3.41, `max_retries=0`, `temperature=0`; Cartesia `sonic-3.6`, API version 2026-08-14, voice "Daniel", one context per generation with `continue`, adapter-side drop after cancel (Cartesia cancel only stops contexts that have not started). Docs: Context7 `/websites/developers_deepgram`, `/websites/cartesia_ai` (2026-10-29); prices deepgram.com/pricing ($0.0077/min nova-3 streaming) and cartesia.ai/pricing (1 credit/char; 2/3/5 concurrent TTS on Free/Pro/Startup) | S03-T01 | `providers/deepgram_stt.py`, `openai_compat_llm.py`, `cartesia_tts.py` | `test_live_providers.py` (`-m live`) 7 passed | Done |
| `make_live` refuses without a reservation in the right pool; the server reserves per session (STT 120 s, LLM $0.002, TTS 1,500 chars) and settles actual use | S03-T01 | `providers/factory.py`, `server.py` | `test_make_live_without_a_reservation_raises` | Done |
| Runtime: one `Session` owns floor events, STT queue (50 frames, drop oldest), transcript assembly, generations with a fence, LLM stall timeout 8 s → reprompt, provider error → spoken apology (backoff is S05-T03), sentence chunker + `speechify`, outbound framing (480 samples) with stale checks at the TTS reader and again before each send | S03-T02..T04 | `voicecore/runtime/session.py`, `runtime/text.py` | `test_runtime.py` (9), `test_runtime_text.py` (3) | Done |
| Deviation: no reorder sequencer. One Cartesia context per generation returns audio in text order (contract test "two chunks… in order"), so the plan's "results arriving 2,1,3 are sent 1,2,3" case cannot happen; frames are numbered at send time | S03-T04 | `cartesia_tts.py`, `session.py::_frame` | contract + `test_first_agent_frame_logs…frames_are_in_order` | Done |
| One process clock: `loop.time()` (`voicecore/clock.py`), so looptime fakes it; traces follow SPEC section 5 and drop text fields unless `include_text` | S03-T02 | `clock.py`, `trace.py` | runtime tests | Done |
| Runner: in-process adapter with a FakeClient that renders 20 ms per tick (9a, CI); WSS adapter launching headless SDK clients through the built gateway and the server (9b, benchmarks) | S03-T07 | `harness/runner/inprocess.py`, `runner/wss.py`, `packages/web-sdk/bin/headless-client.ts` | `test_runner_inprocess.py`, Playwright `voice.spec.ts` | Done |
| Latency is computed without subtracting clocks across processes: total on the client clock, the endpoint placed on the client clock through the triggering frame's `capture_us`, stages on the orchestrator clock, residual derived | S03-T06 | `harness/timeline.py::turn_breakdown` | `test_turn_breakdown…` | Done |

## Execution record

| Task ID | Status | Output paths | Test command/results | Blocker |
|---|---|---|---|---|
| S03-T01 | Done 2026-10-30 | `voicecore/providers/` | `uv run pytest services/agent-core/tests/test_provider_contracts.py` → 6 passed (mock); `uv run pytest -m live -p no:randomly services/agent-core/tests/test_live_providers.py` → 7 passed (STT key words, bad keys fatal ×3, LLM ≤ 80 tokens, TTS gen tags + no audio after cancel); live spend $0.01 + 138 credits | One live STT run ended on an interim; fixed by promoting it (3 reruns pass) |
| S03-T02 | Done 2026-10-30 | `voicecore/runtime/session.py` | `test_runtime.py`: late LLM token never sent; late TTS audio from a provider that ignores cancel is dropped (mutation: removing the stale check fails it); endpoint → gen 1, text.input while thinking cancels 1 and starts 2; client.resumed cancels; hypothesis 40 random sequences on looptime: one live generation, every frame belongs to the newest generation, cancels increase | — |
| S03-T03 | Done 2026-10-30 | `runtime/text.py`, `session.py` | revising interims + final → the LLM gets the final text once; 8 s LLM stall → reprompt spoken (not before 7.9 s); 2 s of mic frames reach STT during a stall with 0 drops | — |
| S03-T04 | Done 2026-10-30 | `runtime/text.py`, `session.py` | 2 sentences → 2 chunks; URL and [1] never split; speechify drops citations and raw URLs; `tts.first_audio` traced once; frame sequence 0..n with end flag | Sequencer not needed (see register) |
| S03-T05 | Done 2026-10-30 | `harness/tests/test_concurrency.py` | 20 sessions, seed 7, random LLM/TTS delays, 15 % HTTP 429, 10 % stalls, fake time: every last generation spoken and played to the end, all sessions ended, STT queues bounded (50) with 0 drops, no asyncio task left, finished within 30 s of fake time after the longest clip | — |
| S03-T06 | Done 2026-10-30 (live, n = 10) | `reports/latency_breakdown.md`, `benchmarks/raw/wss_live_20261030T010848Z/`, baseline rerun `benchmarks/raw/baseline_20261030T011208Z-46df14.jsonl` | speech end → first rendered agent audio p50 2,073 / p95 2,472 ms; endpoint 860, STT settle 0.6, LLM TTFT 595, TTS first audio 572, residual 16 ms (p50). Voice Agent rerun: 4/4 turns, 972 ms median (n = 3, not matched). Spend $0.022 + 1,141 credits; baseline $0.075 | — |
| S03-T07 | Done 2026-10-30 | `voicecore/server.py`, `harness/runner/`, `packages/web-sdk/bin/headless-client.ts`, `apps/demo/e2e/voice.spec.ts` | in-process `dev_single_01`: endpoint, gen 1, mock audio played to the end; silence clip starts nothing. WSS mock run (`benchmarks/raw/wss_mock_20261030T010728Z/`): every span present, residual ±6 ms. Playwright: browser fake mic → gateway → orchestrator → `transcript.final`, `agent.text`, `playout.started` | Found and fixed: the first session loaded the VAD model inline (now preloaded); headless client sent frames 20 ms early |

## Source and artifact change record

| Consumed artifact | Revision or hash | Affected task(s) | Revalidation decision |
|---|---|---|---|
| Code review (medium, `1065378..75726d9`, Steps 02–03): 10 findings, all fixed: mid-stream `openai.APIError` escaped; TTS cap/error left a generation stuck or silenced the session; LLM reservation not enforced and cancelled streams not billed or closed; 120 s STT cap spent on silence (STT now gets speech + 300 ms pre-roll + 600 ms hangover); trace files never closed; latency breakdown could pair an earlier endpoint with a later generation; `speechify` stripped `_` and `#` from identifiers; fence duplicated as growing sets; `power()` copied in 3 places | review 2026-10-30 | S02-T03, S03-T01..T07 | regression tests added; live contracts re-run 7 passed |
| `docs/adr/0001-engine-ownership.md` | provider rows confirmed 2026-10-30 | S03-T01 | updated |
| `packages/protocol/SPEC.md` | v1 | S03-T02, T07 | consumed unchanged |
| `docs/adr/0002-turn-policy.md` | fixed 800 ms | S03-T06, T07 | default `Policy()` used |

## Handoff

Update the registers with real paths and verification. The next step must read the latest output contracts, selected provider configurations and actual evidence. Any change to a prior artifact requires impact review and focused revalidation; the next step must not hard-code an old value copied from this document.
