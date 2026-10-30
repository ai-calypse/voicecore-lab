# Step 06: Observability Evals And Load

**Status:** Complete (2026-10-30), except the manual 20-answer audit (`reports/answer_audit.md`, needs the project owner).  
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

**Outcome / implementation:** The trace event schema is defined in `packages/protocol/SPEC.md` during Step 01 (decision 2026-10-29, see [build plan](./IMPLEMENTATION_PLAN.md)); this task completes emitters in every process and the timeline merge, with speech content redacted by default.  
**Inputs:** This document, [master](./voicecore_lab_career_aligned_plan.md), current upstream records and working code.  
**Dependencies:** None beyond prerequisites.  
**Expected artifacts:** `packages/protocol/SPEC.md (trace schema), services/agent-core/voicecore/trace.py, harness/timeline.py` (planned; actual paths may be selected in owner register).  
**Edge/failure concerns:** Handle invalid input, task cancellation, empty data and path/session lifecycle where applicable; explicitly mark any scenario that is genuinely not applicable.  
**Acceptance test:** Trace exemplars reconstruct each turn without retaining raw audio.  

### S06-T02 — Live timeline UI

**Outcome / implementation:** Create development timeline with stage bars, microphone/agent speaking states and dropped frames.  
**Inputs:** This document, [master](./voicecore_lab_career_aligned_plan.md), current upstream records and working code.  
**Dependencies:** S06-T01.  
**Expected artifacts:** `apps/demo (?lab=1 panel)` (planned; actual paths may be selected in owner register).  
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
**Expected artifacts:** `harness/bench.py` (planned; actual paths may be selected in owner register).  
**Edge/failure concerns:** Handle invalid input, task cancellation, empty data and path/session lifecycle where applicable; explicitly mark any scenario that is genuinely not applicable.  
**Acceptance test:** No simulated client/server clocks merged without sync method; raw CSV/JSON included.  

### S06-T05 — Quality evaluation

**Outcome / implementation:** Score transcription WER, task correctness, unsupported-answer refusal, cited-source validity and interruptions.  
**Inputs:** This document, [master](./voicecore_lab_career_aligned_plan.md), current upstream records and working code.  
**Dependencies:** S06-T04.  
**Expected artifacts:** `harness/timeline.py (quality metrics) and reports/quality_eval.md` (planned; actual paths may be selected in owner register).  
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
| Every process writes the SPEC section 5 trace shape: orchestrator (`voicecore/trace.py`), gateway (`-trace` flag, session lifecycle, `fence`, `agent_first_frame`), client logs converted by the timeline builder | S06-T01 | `trace.py`, `services/realtime-gateway/session/server.go::trace`, `harness/session_timeline.py` | `TestTraceEventsFollowTheSpecSchema`, `test_timeline.py` | Done |
| Clock alignment: client↔gateway by NTP-style ping/pong (min round trip); client→orchestrator derived from mic frames (min arrival − capture end, every 5 s, includes the smallest uplink delay); reference clock = client | S06-T01 | `timeline.py::ntp_offset, merge`, `Session.on_frame` `clock.client_offset` | `test_three_logs_with_a_known_12ms_offset…` | Done |
| Lab panel: plain TS + SVG in `apps/demo` (`?lab=1`, `?trace=<url>`, file load); speaking lanes, 5 stage rows, interrupted generations hatched + labelled (not colour alone), counters, filterable events; light/dark tokens. `frontend-design` skill is not installed in this session; `ui-taste` (uizze) used; no image tool authorised, so built from the brief and inspected at 1280×860 light/dark and 390×844 | S06-T02 | `apps/demo/src/lab.ts`, `lab.css`, `public/lab/sample-timeline.json` (from `harness/lab_sample.py`, fake-provider) | Playwright `lab.spec.ts` | Done |
| Endpoint trace carries `silence_ms`, so the timeline can draw the endpoint wait | S06-T02 | `turntaking/floor.py::Event.silence_ms` | `test_fixed_700…` | Done |
| Scenario simulator: in-process runner takes one-way network delay (both directions, ordered), seeded pink noise at an SNR, and N parallel users | S06-T03 | `harness/runner/inprocess.py` (`run_clip`, `run_users`, `with_noise`) | `test_scenarios.py` | Done |
| Benchmarks: fake n = 216 (`harness/bench.py`); live n = 30 with a `--policy` server flag; WER with real-time pacing (`harness/wer_eval.py`, jiwer); load via `wss.py --parallel` | S06-T04..T06 | `harness/`, `reports/perf.md`, `reports/quality_eval.md` | reports | Done |
| CI regression gate: fixed in-process scenario set, thresholds = measurement + 100 ms; `evals.yml` | S06-T06 | `harness/gate.py`, `harness/thresholds.json`, `.github/workflows/evals.yml` | proof branch `ci-gate-proof` failed the gate in CI | Done |
| Live budget: Cartesia credits reached 10,877 of 16,000 after Step 06 (Step 05 overran); Step 08 has about 5,100 left | S06-T04 | `benchmarks/spend_ledger.json` | ledger | Watch |

## Execution record

| Task ID | Status | Output paths | Test command/results | Blocker |
|---|---|---|---|---|
| S06-T01 | Done 2026-10-30 | `harness/timeline.py`, `harness/session_timeline.py`, gateway `-trace` | 12 ms offset merge order + aligned times literal; no text unless include_text; gateway trace schema test; mock WSS session timeline: 28 events from 3 processes in causal order (one 0.2 ms inversion within the derived offset's error) | — |
| S06-T02 | Done 2026-10-30 | `apps/demo/src/lab.ts`, `lab.css`, `apps/demo/e2e/lab.spec.ts` | Playwright: 5 stage rows, all 5 bars for gen 2, gen 1 marked interrupted, process filter hides gateway rows; screenshots inspected (desktop light/dark, phone light); phone table squeeze fixed | `frontend-design` not available; built with `ui-taste` |
| S06-T03 | Done 2026-10-30 | `harness/runner/inprocess.py` | 2 users, seed 7, 40 ms one-way delay, 15 dB noise: 2 complete sessions, identical logs on rerun (1 ms resolution) | — |
| S06-T04 | Done 2026-10-30 | `harness/bench.py`, `reports/perf.md`, `reports/perf_fake.json`, `benchmarks/raw/wss_live_{fixed,asr_assisted}_*` | Fake 216 turns: total p50/p95/p99 1,320/1,440/1,480 ms, 0 early, 0 drops. Live 30: fixed p50 2,317 / p95 3,102 ms, 15/15 whole; asr_assisted decides 340 ms sooner, 3/15 split. Cost per live turn $0.00083 STT + $0.00013 LLM + 138 credits | — |
| S06-T05 | Done 2026-10-30 (manual audit open) | `harness/wer_eval.py`, `reports/quality_eval.md`, `reports/wer_holdout.json`, `reports/answer_audit.md` | WER 6.5 % on 25 holdout clips (docs questions 3.2 %); found and fixed: fast streaming lost clip endings (9.9 %); answers from S04-T05 | 20-answer manual audit needs the project owner |
| S06-T06 | Done 2026-10-30 | `harness/gate.py`, `harness/thresholds.json`, `.github/workflows/evals.yml`, `benchmarks/raw/wss_mock_fixed_*` | Mock load 1/5/20/40 sessions all complete, p95 1,301–1,320 ms, 0 drops; live 2 concurrent complete; gate passes on main, fails with +200 ms (CI run 40991626127) | Live load above 2 sessions not run (Cartesia plan, budget) |

## Source and artifact change record

| Consumed artifact | Revision or hash | Affected task(s) | Revalidation decision |
|---|---|---|---|
| `packages/protocol/SPEC.md` section 5 trace schema | v1 | S06-T01 | consumed unchanged |
| `docs/adr/0002-turn-policy.md` | live check added | S06-T04 | default kept |

## Handoff

Update the registers with real paths and verification. The next step must read the latest output contracts, selected provider configurations and actual evidence. Any change to a prior artifact requires impact review and focused revalidation; the next step must not hard-code an old value copied from this document.
