# Step 00: Career Evidence And Baselines

**Status:** In progress. S00-T01 done (2026-10-29); S00-T02 blocked on approval for live paid provider use.  
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
| Workspace is not a git repository; no commit IDs can be recorded until the user runs `git init` | Master guide §5 step 1 | Repository root | `git status` fails: not a git repository | Open |

## Execution record

| Task ID | Status | Output paths | Test command/results | Blocker |
|---|---|---|---|---|
| S00-T01 | Done 2026-10-29 | requirements matrix (kept private) | per-role proof count and task-ID existence check passed | — |
| S00-T02 | Blocked | — | — | Needs user approval for live paid provider usage and a choice of hosted baseline. Only `DEEPGRAM_API_KEY` is present. |
| S00-T03 | Not started | — | — | — |
| S00-T04 | Not started | — | — | — |

## Source and artifact change record

| Consumed artifact | Revision or hash | Affected task(s) | Revalidation decision |
|---|---|---|---|
| `MASTER_AGENT_GUIDE.md` | sha256 `102cf19eeea4…` | S00-T01 | Consumed as is |
| `docs/voicecore_lab_career_aligned_plan.md` | sha256 `55abdc31de7d…` | S00-T01 | Consumed as is |
| `docs/README.md` | sha256 `43a4338f4c9d…` | S00-T01 | Consumed as is |
| `docs/step_01` … `step_08` (Expected artifacts and acceptance tests) | sha256 `b977e03d20c8…`, `5ef53bea9704…`, `eb723b7c792e…`, `5f0d201d810c…`, `e24eb302694b…`, `67ca6f7a3e74…`, `6596a0e72db5…`, `d741488bad4c…` | S00-T01 | Planned paths copied into matrix; owning steps may change them and must update the matrix |

## Handoff

Update the registers with real paths and verification. The next step must read the latest output contracts, selected provider configurations and actual evidence. Any change to a prior artifact requires impact review and focused revalidation; the next step must not hard-code an old value copied from this document.
