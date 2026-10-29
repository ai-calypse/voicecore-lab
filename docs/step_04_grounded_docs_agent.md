# Step 04: Grounded Docs Agent

**Status:** Planned; no implementation or test evidence yet.  
**Estimated engineering effort:** 25 hours.  
**Task owner:** Implementation agent; user confirms external paid credentials.  

## Purpose and scope

Use documentation questions to demonstrate correct tool invocation, provenance and shared text/voice logic. Focus on ownership and evidence, not cosmetic product polish. Follow the global project non-goals in [master plan](./voicecore_lab_career_aligned_plan.md#explicit-non-goals).

## Step-specific implementation-agent prompt

> Act as a senior real-time voice software engineer. Read this step, the canonical [plan](./voicecore_lab_career_aligned_plan.md), [process](./README.md#source-of-truth-and-change-detection), and referenced previous step outputs. Inspect the existing code and prior execution records. Implement all remaining tasks in dependency order, verify with real commands and tests, record actual evidence/paths, and stop at this step's exit gate. Never invent pass results, provider support, latency numbers or source files.

## Required reading and prerequisites

- [Master architecture and contracts](./voicecore_lab_career_aligned_plan.md#system-architecture)
- [Previous step](./step_03_streaming_orchestrator.md) and its actual outputs, not merely planned files.
- Exact upstream code artifacts and ADRs named in the tasks below; if missing, record blocker and do independent preparations only.

## Decision ownership

This step owns the task-specific implementation choices, contracts and test evidence described below. It inherits the public goals, constraints, budget philosophy, evaluation thresholds and overall stack from the master plan. Do not silently change cross-step contracts. If needed, update the responsible upstream ADR/document and mark affected work for review.

## Phases and specific tasks

### S04-T01 — Docs ingestion

**Outcome / implementation:** Ingest static Markdown and public HTML sitemap with canonical URLs, content hashes and safe parsing; avoid internal URLs.  
**Inputs:** This document, [master](./voicecore_lab_career_aligned_plan.md), current upstream records and working code.  
**Dependencies:** None beyond prerequisites.  
**Expected artifacts:** `services/agent-core/voicecore/answer (ingest)` (planned; actual paths may be selected in owner register).  
**Edge/failure concerns:** Handle invalid input, task cancellation, empty data and path/session lifecycle where applicable; explicitly mark any scenario that is genuinely not applicable.  
**Acceptance test:** Fixture runs are deterministic; SSRF and instruction-text tests pass.  

### S04-T02 — Hybrid retrieval

**Outcome / implementation:** Implement lexical + dense retrieval with reciprocal rank fusion, passage metadata and versioned snapshot.  
**Inputs:** This document, [master](./voicecore_lab_career_aligned_plan.md), current upstream records and working code.  
**Dependencies:** S04-T01.  
**Expected artifacts:** `services/agent-core/voicecore/answer (index: FTS5 + fastembed + RRF)` (planned; actual paths may be selected in owner register).  
**Edge/failure concerns:** Handle invalid input, task cancellation, empty data and path/session lifecycle where applicable; explicitly mark any scenario that is genuinely not applicable.  
**Acceptance test:** Golden corpus eval logs Recall@K/MRR plus citations; no ungrounded passages.  

### S04-T03 — Tool contract + answer schema

**Outcome / implementation:** Expose docs.search tool with supported/unanswered distinction and exact URL fragment citation IDs.  
**Inputs:** This document, [master](./voicecore_lab_career_aligned_plan.md), current upstream records and working code.  
**Dependencies:** S04-T02.  
**Expected artifacts:** `services/agent-core/voicecore/answer (docs.search tool, citation validator)` (planned; actual paths may be selected in owner register).  
**Edge/failure concerns:** Handle invalid input, task cancellation, empty data and path/session lifecycle where applicable; explicitly mark any scenario that is genuinely not applicable.  
**Acceptance test:** Tool output cannot invent URL; response schema validated before speaking.  

### S04-T04 — Shared text + voice semantics

**Outcome / implementation:** Text and voice turns invoke same answer/tool engine; speech output strips awkward citation syntax.  
**Inputs:** This document, [master](./voicecore_lab_career_aligned_plan.md), current upstream records and working code.  
**Dependencies:** S04-T03.  
**Expected artifacts:** `services/agent-core/voicecore/answer (answer(), speechify())` (planned; actual paths may be selected in owner register).  
**Edge/failure concerns:** Handle invalid input, task cancellation, empty data and path/session lifecycle where applicable; explicitly mark any scenario that is genuinely not applicable.  
**Acceptance test:** Parity tests compare citations and factual claims in text vs voice.  

### S04-T05 — Adversarial eval

**Outcome / implementation:** Run stale/contradictory docs, prompt injection, unauthorized sources and unsupported questions.  
**Inputs:** This document, [master](./voicecore_lab_career_aligned_plan.md), current upstream records and working code.  
**Dependencies:** S04-T04.  
**Expected artifacts:** `reports/docs_eval.md` (planned; actual paths may be selected in owner register).  
**Edge/failure concerns:** Handle invalid input, task cancellation, empty data and path/session lifecycle where applicable; explicitly mark any scenario that is genuinely not applicable.  
**Acceptance test:** Evidence for correct refusal and cite validity with a held-out dataset.  

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
| S04-T01 | Not started | — | — | — |
| S04-T02 | Not started | — | — | — |
| S04-T03 | Not started | — | — | — |
| S04-T04 | Not started | — | — | — |
| S04-T05 | Not started | — | — | — |

## Source and artifact change record

| Consumed artifact | Revision or hash | Affected task(s) | Revalidation decision |
|---|---|---|---|
| TBD | TBD | TBD | TBD |

## Handoff

Update the registers with real paths and verification. The next step must read the latest output contracts, selected provider configurations and actual evidence. Any change to a prior artifact requires impact review and focused revalidation; the next step must not hard-code an old value copied from this document.
