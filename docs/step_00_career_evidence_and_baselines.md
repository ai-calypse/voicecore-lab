# Step 00: Career Evidence And Baselines

**Status:** Complete (2026-10-29). S00-T01–T04 done. The user declined the 10 own-voice recordings and waived the listen/read checks (2026-10-29); holdout docs questions use the Aura holdout voice only.  
**Estimated engineering effort:** 12 hours.  
**Task owner:** Implementation agent; user confirms external paid credentials.  

## Purpose and scope

Translate job evidence into measurable engineering goals, run provider-neutral baseline and define test fixture boundaries. Focus on ownership and evidence, not cosmetic product polish. Follow the global project non-goals in [master plan](./voicecore_lab_career_aligned_plan.md#explicit-non-goals).

## Step-specific implementation-agent prompt

> Act as a senior real-time voice software engineer. Read this step, the canonical [plan](./voicecore_lab_career_aligned_plan.md), [process](./README.md#source-of-truth-and-change-detection), and referenced previous step outputs. Inspect the existing code and prior execution records. Implement all remaining tasks in dependency order, verify with real commands and tests, record actual evidence/paths, and stop at this step's exit gate. Never invent pass results, provider support, latency numbers or source files.

## Provider baseline to honor

Before implementing this step, read the canonical [initial voice-model provider decisions](./voicecore_lab_career_aligned_plan.md#initial-voice-model-providers-default-integrations-not-hard-vendor-lock-in). Do not invent specific SDK methods, freeze unknown model IDs, claim that a provider was integrated, or bypass the replaceable adapter design. Verify current official streaming contracts and record selected model/API revisions in this step's decision register before any live provider usage.

## Required reading and prerequisites

- [Master architecture and contracts](./voicecore_lab_career_aligned_plan.md#system-architecture)
- No previous implementation step.
- Exact upstream code artifacts and ADRs named in the tasks below; if missing, record blocker and do independent preparations only.

## Decision ownership

This step owns the task-specific implementation choices, contracts and test evidence described below. It inherits the public goals, constraints, budget philosophy, evaluation thresholds and overall stack from the master plan. Do not silently change cross-step contracts. If needed, update the responsible upstream ADR/document and mark affected work for review.

## Phases and specific tasks

### S00-T01 — Requirement traceability

**Outcome / implementation:** Map each selected role requirement to a concrete owned subsystem, test and demo artifact (a requirements matrix kept outside the public repository).  
**Inputs:** This document, [master](./voicecore_lab_career_aligned_plan.md), current upstream records and working code.  
**Dependencies:** None beyond prerequisites.  
**Expected artifacts:** `requirements matrix (kept private); no unverified claims` (planned; actual paths may be selected in owner register).  
**Edge/failure concerns:** Handle invalid input, task cancellation, empty data and path/session lifecycle where applicable; explicitly mark any scenario that is genuinely not applicable.  
**Acceptance test:** Each selected role has >=2 concrete engineering proofs or a documented out-of-scope reason.  

### S00-T02 — Control baseline

**Outcome / implementation:** Implement a minimal hosted provider-led voice + text docs answer as a comparison only; measure connect, speech-end to audible start, and turn success.  
**Inputs:** This document, [master](./voicecore_lab_career_aligned_plan.md), current upstream records and working code.  
**Dependencies:** S00-T01.  
**Expected artifacts:** `benchmarks/baseline_results.json and harness/config/baseline.yaml` (planned; actual paths may be selected in owner register).  
**Edge/failure concerns:** Handle invalid input, task cancellation, empty data and path/session lifecycle where applicable; explicitly mark any scenario that is genuinely not applicable.  
**Acceptance test:** A real reproducible baseline trace exists; no benchmark asserted before measurement.  

### S00-T03 — Audio and docs fixtures

**Outcome / implementation:** Prepare licensed/consented WAV/PCM fixtures: silence, single speaker, interruptions, noise, slow speech, docs Q&A and unsupported questions.  
**Inputs:** This document, [master](./voicecore_lab_career_aligned_plan.md), current upstream records and working code.  
**Dependencies:** S00-T02.  
**Expected artifacts:** `fixtures/audio/ manifest + fixtures/docs/ pages + answer_key.json` (planned; actual paths may be selected in owner register).  
**Edge/failure concerns:** Handle invalid input, task cancellation, empty data and path/session lifecycle where applicable; explicitly mark any scenario that is genuinely not applicable.  
**Acceptance test:** Fixtures validated, provenance documented, holdout separated from development.  

### S00-T04 — Architecture decision record

**Outcome / implementation:** Choose Go custom engine + Python adapters + TypeScript SDK, document why commercial voice-agent frameworks are baseline only.  
**Inputs:** This document, [master](./voicecore_lab_career_aligned_plan.md), current upstream records and working code.  
**Dependencies:** S00-T03.  
**Expected artifacts:** `docs/adr/0001-engine-ownership.md` (planned; actual paths may be selected in owner register).  
**Edge/failure concerns:** Handle invalid input, task cancellation, empty data and path/session lifecycle where applicable; explicitly mark any scenario that is genuinely not applicable.  
**Acceptance test:** ADR identifies code owned, purchased external model inference and explicit non-goals.  

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
| Requirements matrix, kept outside the public repository: each role mapped to an owned subsystem, test task and report artifact; uncovered signals listed instead of stretched proofs | S00-T01 | private | — | Done |
| Provider credentials live only in root `.env` (`DEEPGRAM_API_KEY`, mode 600), ignored by `.gitignore`; never sent to the browser | Master plan security and privacy | `.env`, `.gitignore` | — | Done; no other provider keys yet |
| Git repository created at user request: private `github.com/ai-calypse/voicecore-lab`, branch `main` | Master guide §5 step 1 | Repository root | First commit `59a8c2b` | Done |
| Hosted control baseline = Deepgram Voice Agent API (`wss://agent.deepgram.com/v1/agent/converse`), Standard tier: listen `deepgram nova-3`, think `open_ai gpt-4o-mini` (temperature 0), speak `deepgram v2 flux-kit-en`; input linear16 16 kHz, output linear16 24 kHz. Verified 2026-10-29 from Deepgram docs (Settings, events, error codes, LLM tiers) and the live `GET /v1/agent/settings/think/models` listing | S00-T02 / master plan provider baseline | `harness/config/baseline.json` | `benchmarks/baseline_results.json` | Done |
| Paid usage approved by user 2026-10-29 with a $2.00 cap. Guard: before each session, ledger total + worst case (`max_session_seconds` 120 s, rounded up to whole minutes at $0.075/min list price) must stay ≤ $2.00. The key lacks `billing:read`, so the ledger is a conservative local estimate, not Deepgram's billed amount | S00-T02 | `harness/baseline_deepgram.py` (`can_afford`, `session_cost`), `benchmarks/spend_ledger.json` | Ledger total $0.525 after 7 sessions | Done |
| Config is JSON, not the planned YAML, so the harness needs only the stdlib plus `websockets` (PEP 723 inline deps, run with `uv run`) | S00-T02 | `harness/config/baseline.json` | — | Done |
| Baseline speech inputs are synthetic macOS `say` (voice Samantha, PCM16 16 kHz), generated into gitignored `.cache/` and identified by SHA-256 in results. Not committed: Apple voice output is licensed for personal non-commercial use; S00-T03 decides the licensed fixture set | S00-T02 / S00-T03 | `.cache/baseline_audio/` | `fixtures` block in `benchmarks/baseline_results.json` | Done; T03 to replace |
| Measurement definitions: one client monotonic clock; speech end = send time of last fixture frame with peak ≥ 500, real-time paced 20 ms frames; first audio = first binary agent frame received (**not acoustic playback**, no playout buffer); text turn timed from `InjectUserMessage` send; success = `AgentAudioDone` + audio + assistant text matching the keyword key; turn success rate counts turns lost to failed sessions | S00-T02 | `harness/baseline_deepgram.py` | `measurement_notes` in results | Done |
| After the smoke run, turn 1 question changed to "What audio format and sample rate does the browser send?" because the key required the sample rate the question did not ask for (agent answered "PCM16 mono"). Key unchanged | S00-T02 | `harness/config/baseline.json` | Trace `benchmarks/raw/baseline_20261029T180524Z-a0e15d.jsonl` | Done |
| `LatencyReport` arrives as one field per message; harness merges them per turn | S00-T02 | `harness/baseline_deepgram.py` receiver | Same trace | Done |
| 5 s gap between sessions after back-to-back `FAILED_TO_START_LISTENING`; the gap did not remove the failure (see execution record) | S00-T02 | `session_gap_seconds` in config | Runs `…180621Z-662a2e`, `…180728Z-a29514` | Open: root cause unknown; investigated before Step 03 adapters |
| Audio fixtures from LibriSpeech (CC BY 4.0): dev = dev-clean, holdout = test-clean (disjoint speakers); 12–24-word utterances, seed 42; trimmed to first/last 20 ms window with peak ≥ 500, padded 1.0 s / 1.5 s so labels are exact; categories silence, single, noisy_10db (pink), noisy_5db (brown), slow_0_8x, mid_pause_600ms, interrupt, echo_only | S00-T03 / plan S00-T03 | `harness/build_fixtures.py`, `fixtures/audio/manifest.json`, `fixtures/audio/ATTRIBUTION.md` | `harness/tests/test_fixtures.py` | Done |
| Agent voice for echo/interrupt clips is a reserved LibriSpeech speaker per split (dev 1272 from dev-clean, holdout 1089 from test-clean), not Aura, so those clips can be committed and tested in CI and no audio is shared between splits | S00-T03 | `fixtures/audio/ref/` | same | Done (deviation from plan: Aura agent voice) |
| Deepgram Aura output redistribution terms could not be confirmed (terms pages 404); Aura docs-question clips (dev voice `aura-2-apollo-en`, holdout `aura-2-luna-en`) and the user's recordings stay local in gitignored `fixtures/audio/local/` | S00-T03 | `harness/build_local_fixtures.py`, `fixtures/audio/local/manifest.json` | `test_every_docs_question_has_local_audio_in_a_split_specific_voice` (skips in CI) | Done |
| Noise is generated with numpy (seeded) instead of ffmpeg `anoisesrc`; same determinism, fewer moving parts | S00-T03 | `harness/build_fixtures.py::noise` | rebuild gives identical manifest | Done |
| LibriSpeech tarballs kept in `.cache/librispeech/` (683 MB, gitignored) so the builder can rerun without a download; plan said delete them | S00-T03 | `.cache/` | — | User may delete |
| Docs corpus: astral-sh/uv docs at tag 0.13.6 (`329bf94`), 81 Markdown files, MIT OR Apache-2.0; answer key 40 questions (30 answerable, 10 unanswerable; dev 25 / holdout 15; 10 marked for user recording) | S00-T03 | `fixtures/docs/uv/`, `fixtures/docs/answer_key.json` | `test_answer_key_cites_sections_that_exist_and_contain_the_key_terms` | Done |
| ADR 0001 engine ownership written | S00-T04 | `docs/adr/0001-engine-ownership.md` | `grep -c "^## "` = 5 | Done |
| User declined recording the 10 holdout questions and waived the 5-clip listen and ADR read (2026-10-29). Holdout docs-question audio = Aura `aura-2-luna-en` for all 15 holdout questions; `user_record` flags in the answer key are inert; `harness/record_questions.md` stays as an optional path | S00-T03 handoff | `fixtures/audio/local/manifest.json` | `test_every_docs_question_has_local_audio_in_a_split_specific_voice` passes | Done (user decision) |

## Execution record

| Task ID | Status | Output paths | Test command/results | Blocker |
|---|---|---|---|---|
| S00-T01 | Done 2026-10-29 | requirements matrix (kept private) | per-role proof count and task-ID existence check passed | — |
| S00-T02 | Done 2026-10-29 (live provider, measured) | `harness/baseline_deepgram.py`, `harness/config/baseline.json`, `benchmarks/baseline_results.json` (latest run only), `benchmarks/raw/baseline_*.jsonl` (all runs), `benchmarks/spend_ledger.json` | `uv run harness/baseline_deepgram.py --self-test` → `self-test ok` (budget, scoring, framing). Live runs, unshaped residential WAN, default US endpoint, macOS 26.5.2, Python 3.12 via uv: **(1)** `…180524Z-a0e15d`, 1 session, 3/4 turns (key mismatch, fixed above). **(2)** `…180621Z-662a2e`, 3 sessions: session 0 4/4, sessions 1–2 `FAILED_TO_START_LISTENING` at setup, back to back. **(3)** `…180728Z-a29514`, 3 sessions, 5 s gap: sessions 0–1 4/4, session 2 `FAILED_TO_START_LISTENING`. Run 3 results: turn success 8/12 = 0.667 (all 8 attempted turns passed; 4 lost to the failed session); voice speech end → first agent audio frame min/median/max 932.0 / 1094.8 / 1175.6 ms (n=6); text inject → first audio 968.3 / 1016.3 / 1064.3 ms (n=2); WS open 248.3 / 249.1 / 263.8 ms (n=3); SettingsApplied 327.9 / 340.8 ms (n=2). Deepgram's own `total_latency` per turn 0.90–1.15 s. Session setup failed in 3 of 7 sessions overall. Small sample: no percentiles claimed | Open finding: intermittent `FAILED_TO_START_LISTENING` (failed request IDs in `benchmarks/spend_ledger.json`); acoustic playback start not measured (headless client) |
| S00-T03 | Done 2026-10-29 | `fixtures/audio/` (43 committed clips, 11.9 MB), `fixtures/audio/local/` (40 Aura clips, local only), `fixtures/docs/`, `harness/build_fixtures.py`, `harness/build_local_fixtures.py`, `harness/fixtures.py`, `harness/record_questions.md` | `uv run pytest harness/tests` → 10 passed. Each check was shown to fail on a deliberately broken manifest (8/8 caught). Rebuild is byte-identical. Code review (medium) found dev/holdout echo clips were byte-identical and holdout reused the dev agent voice; fixed with one agent speaker per split and a new no-shared-audio test, plus fixes for repeat Aura spend, quiet-audio crash, lost manifest on partial failure, keypress in recordings. Aura spend $0.073 (2,447 chars, live-provider) | — (recordings declined by user) |
| S00-T04 | Done 2026-10-29 | `docs/adr/0001-engine-ownership.md` | `grep -c "^## "` → 5 | — |

## Source and artifact change record

| Consumed artifact | Revision or hash | Affected task(s) | Revalidation decision |
|---|---|---|---|
| `MASTER_AGENT_GUIDE.md` | sha256 `102cf19eeea4…` | S00-T01 | Consumed as is |
| `docs/voicecore_lab_career_aligned_plan.md` | sha256 `55abdc31de7d…` | S00-T01 | Consumed as is |
| `docs/README.md` | sha256 `43a4338f4c9d…` | S00-T01 | Consumed as is |
| LibriSpeech dev-clean / test-clean tarballs (openslr.org/12, CC BY 4.0) | sha256 `76f87d09…` / `39fde525…` | S00-T03 | Source of committed fixtures |
| astral-sh/uv docs | tag 0.13.6, commit `329bf944…` | S00-T03 | Snapshot for the answer engine |
| Deepgram Voice Agent docs (Settings, server events, `InjectUserMessage`, `LatencyReport`, error codes, LLM pricing tiers) via Context7 `/websites/developers_deepgram`; `https://deepgram.com/pricing`; live think-models listing | Fetched 2026-10-29 | S00-T02 | Re-verify before Step 03 live adapters |
| `docs/step_01` … `step_08` (Expected artifacts and acceptance tests) | sha256 `b977e03d20c8…`, `5ef53bea9704…`, `eb723b7c792e…`, `5f0d201d810c…`, `e24eb302694b…`, `67ca6f7a3e74…`, `6596a0e72db5…`, `d741488bad4c…` | S00-T01 | Planned paths copied into matrix; owning steps may change them and must update the matrix |

## Handoff

Update the registers with real paths and verification. The next step must read the latest output contracts, selected provider configurations and actual evidence. Any change to a prior artifact requires impact review and focused revalidation; the next step must not hard-code an old value copied from this document.
