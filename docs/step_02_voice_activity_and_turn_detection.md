# Step 02: Voice Activity And Turn Detection

**Status:** Complete (2026-10-30), except the manual speaker/AEC check in S02-T03, which needs a person and speakers (open).  
**Estimated engineering effort:** 30 hours.  
**Task owner:** Implementation agent; user confirms external paid credentials.  

## Purpose and scope

Implement and compare turn detection policies that trade latency against false turn endings. Focus on ownership and evidence, not cosmetic product polish. Follow the global project non-goals in [master plan](./voicecore_lab_career_aligned_plan.md#explicit-non-goals).

## Step-specific implementation-agent prompt

> Act as a senior real-time voice software engineer. Read this step, the canonical [plan](./voicecore_lab_career_aligned_plan.md), [process](./README.md#source-of-truth-and-change-detection), and referenced previous step outputs. Inspect the existing code and prior execution records. Implement all remaining tasks in dependency order, verify with real commands and tests, record actual evidence/paths, and stop at this step's exit gate. Never invent pass results, provider support, latency numbers or source files.

## Provider baseline to honor

Before implementing this step, read the canonical [initial voice-model provider decisions](./voicecore_lab_career_aligned_plan.md#initial-voice-model-providers-default-integrations-not-hard-vendor-lock-in). Do not invent specific SDK methods, freeze unknown model IDs, claim that a provider was integrated, or bypass the replaceable adapter design. Verify current official streaming contracts and record selected model/API revisions in this step's decision register before any live provider usage.

## Required reading and prerequisites

- [Master architecture and contracts](./voicecore_lab_career_aligned_plan.md#system-architecture)
- [Previous step](./step_01_audio_transport_and_sdk.md) and its actual outputs, not merely planned files.
- Exact upstream code artifacts and ADRs named in the tasks below; if missing, record blocker and do independent preparations only.

## Decision ownership

This step owns the task-specific implementation choices, contracts and test evidence described below. It inherits the public goals, constraints, budget philosophy, evaluation thresholds and overall stack from the master plan. Do not silently change cross-step contracts. If needed, update the responsible upstream ADR/document and mark affected work for review.

## Phases and specific tasks

### S02-T01 — Streaming VAD

**Outcome / implementation:** Integrate a VAD as a replaceable primitive and build voiced/unvoiced segment state machine.  
**Inputs:** This document, [master](./voicecore_lab_career_aligned_plan.md), current upstream records and working code.  
**Dependencies:** None beyond prerequisites.  
**Expected artifacts:** `services/agent-core/voicecore/turntaking (vad_silero.py, vad_fixture.py)` (planned; actual paths may be selected in owner register).  
**Edge/failure concerns:** Handle invalid input, task cancellation, empty data and path/session lifecycle where applicable; explicitly mark any scenario that is genuinely not applicable.  
**Acceptance test:** Fixtures cover silence, noisy environment, soft voice and zero speech.  

### S02-T02 — Endpointing policies

**Outcome / implementation:** Implement fixed trailing silence, adaptive silence and ASR-assisted endpointing with hysteresis and max utterance.  
**Inputs:** This document, [master](./voicecore_lab_career_aligned_plan.md), current upstream records and working code.  
**Dependencies:** S02-T01.  
**Expected artifacts:** `services/agent-core/voicecore/turntaking (floor module, policy config)` (planned; actual paths may be selected in owner register).  
**Edge/failure concerns:** Handle invalid input, task cancellation, empty data and path/session lifecycle where applicable; explicitly mark any scenario that is genuinely not applicable.  
**Acceptance test:** Policies have independent tests for early cutoff, silence timeout and long utterance.  

### S02-T03 — False wake/echo control

**Outcome / implementation:** Compare browser AEC/noise suppression settings and microphone ducking while TTS is speaking.  
**Inputs:** This document, [master](./voicecore_lab_career_aligned_plan.md), current upstream records and working code.  
**Dependencies:** S02-T02.  
**Expected artifacts:** `benchmarks/turntaking/echo.md` (planned; actual paths may be selected in owner register).  
**Edge/failure concerns:** Handle invalid input, task cancellation, empty data and path/session lifecycle where applicable; explicitly mark any scenario that is genuinely not applicable.  
**Acceptance test:** Echo-only playback does not spuriously increment user turn in curated fixtures.  

### S02-T04 — Turn-taking evaluator

**Outcome / implementation:** Create annotated speech boundaries, score endpoint delay, early cutoff rate and missed utterance rate.  
**Inputs:** This document, [master](./voicecore_lab_career_aligned_plan.md), current upstream records and working code.  
**Dependencies:** S02-T03.  
**Expected artifacts:** `harness/timeline.py and reports/turn_eval.md` (planned; actual paths may be selected in owner register).  
**Edge/failure concerns:** Handle invalid input, task cancellation, empty data and path/session lifecycle where applicable; explicitly mark any scenario that is genuinely not applicable.  
**Acceptance test:** Metrics are computed from labeled references, not model opinion.  

### S02-T05 — Policy report

**Outcome / implementation:** Ablate policies with matched input, plot latency-vs-cutoff tradeoff and choose explicit default.  
**Inputs:** This document, [master](./voicecore_lab_career_aligned_plan.md), current upstream records and working code.  
**Dependencies:** S02-T04.  
**Expected artifacts:** `docs/adr/0002-turn-policy.md` (planned; actual paths may be selected in owner register).  
**Edge/failure concerns:** Handle invalid input, task cancellation, empty data and path/session lifecycle where applicable; explicitly mark any scenario that is genuinely not applicable.  
**Acceptance test:** Selected policy cites measured traces and acknowledges failure cases.  

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
| VAD: Silero v6.2.3 ONNX (MIT, sha256 `1a153a22…8788e3`, committed next to the adapter) on onnxruntime, 1 thread; 20 ms frames buffered into 512-sample windows with 64 samples of context and a [2,1,128] state (interface checked in Context7 `/snakers4/silero-vad`, 2026-10-29) | S02-T01 | `voicecore/turntaking/vad_silero.py` | `test_vad.py` | Done |
| Label-driven fixture VAD for frame-exact floor tests | S02-T01 | `voicecore/turntaking/vad_fixture.py` | `test_floor.py` | Done |
| Floor = one class, policies = config (`fixed`, `adaptive`, `asr_assisted`), time = sample position, decisions stamped at the end of the frame | S02-T02 | `voicecore/turntaking/floor.py` | `test_floor.py` (8) | Done |
| Echo gate while playing: threshold +0.2, 160 ms min speech (plan said 200 ms; that alone exceeds the 200 ms barge-in target), mic 100 ms power ≥ played power − 6 dB (plan said "+6 dB over the reference"; the reference is the played signal, so the echo-loss assumption is folded into −6 dB), 200 ms echo tail after playout stops (found: the echo outlives playout by its 40 ms delay) | S02-T03 | `floor.py` | `test_echo.py` | Done |
| Fixture fix: agent clips and interrupting users set to −23 dBFS; one dev user was 16 dB below the agent, i.e. under the echo | S02-T03 (S00-T03 artifact) | `harness/build_fixtures.py` | rebuilt manifest; `harness/tests` pass | Done |
| Evaluator: nearest-rank percentiles; first endpoint decides early cutoff / miss / delay | S02-T04 | `harness/timeline.py` | `harness/tests/test_timeline.py` (4) | Done |
| Default policy fixed 800 ms | S02-T05 | `Policy()` defaults | `docs/adr/0002-turn-policy.md` | Done |

## Execution record

| Task ID | Status | Output paths | Test command/results | Blocker |
|---|---|---|---|---|
| S02-T01 | Done 2026-10-30 | `voicecore/turntaking/vad_silero.py`, `vad_fixture.py`, `silero_vad.onnx` | `uv run pytest services/agent-core/tests/test_vad.py` → 5 passed: silence < 0.2 on ≥ 95 % of frames (both adapters); prob > 0.5 on ≥ 80 % of speech frames for single, noisy 10 dB, noisy 5 dB, slow 0.8× (both); reset gives identical probabilities | — |
| S02-T02 | Done 2026-10-30 | `voicecore/turntaking/floor.py` | `test_floor.py` → 8 passed: start after 3 voiced frames not 2; fixed 700 ends at ceil20(label end) + 700; mid-pause cut by fixed 400 not adaptive; adaptive 400/700/1000 by speech length; 15 s cap; asr_assisted 400 ms before adaptive; unpunctuated final falls back; late final ends at once | — |
| S02-T03 | Done 2026-10-30 (fixtures); manual check open | `floor.py`, `benchmarks/turntaking/echo.md` | `test_echo.py` → 3 passed: 0 events on both dev echo-only clips; dev interrupts barge in 180/440/160 ms after onset (all ≤ 500, median ≤ 200). Holdout: 0/2 false barge-ins, 180/200 ms | Manual speaker + AEC on/off check needs the user |
| S02-T04 | Done 2026-10-30 | `harness/timeline.py` | `harness/tests/test_timeline.py` → 4 passed (median 200 of [100,300,200]; 50 ms early = cutoff; no endpoint = missed; nearest rank) | — |
| S02-T05 | Done 2026-10-30 | `harness/turn_sweep.py`, `reports/turn_policy.{json,txt,png}`, `reports/turn_policy_holdout.json`, `docs/adr/0002-turn-policy.md` | 13 policies on 12 dev turns; fixed 800: median 860, p95 980, 0 early; holdout once: median 820, p95 880, 1/10 early (long natural pause) | asr_assisted numbers are simulated |

## Source and artifact change record

| Consumed artifact | Revision or hash | Affected task(s) | Revalidation decision |
|---|---|---|---|
| `fixtures/audio/manifest.json` | rebuilt 2026-10-30 with `level_dbfs: -23` | S02-T01..T05 | all fixture tests re-run and pass |
| Silero VAD | v6.2.3, commit `5cd79456`, model sha256 `1a153a22…` | S02-T01 | committed with MIT licence notice in the adapter docstring |

## Handoff

Update the registers with real paths and verification. The next step must read the latest output contracts, selected provider configurations and actual evidence. Any change to a prior artifact requires impact review and focused revalidation; the next step must not hard-code an old value copied from this document.
