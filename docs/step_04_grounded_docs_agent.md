# Step 04: Grounded Docs Agent

**Status:** Complete (2026-10-30). Text and voice share one grounded answer engine; live eval on holdout and two adversarial sets recorded in `reports/docs_eval.md`.  
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
| Ingestion: Markdown split at headings outside code fences; canonical URL = `https://docs.astral.sh/uv/<path>/#<python-markdown slug>` (explicit `{#id}` honoured); id = sha256(url)[:12]; sha256 of text; front matter `source_url` / `version` on crawled pages; pages outside the https allowlist or with a version other than the snapshot (0.13.6) are not indexed; instruction-like text kept but flagged `suspicious` | S04-T01 | `voicecore/answer/ingest.py` | `test_answer_ingest.py` | Done |
| SSRF guard for any URL fetch: https only, allowlisted host (`docs.astral.sh`), no IP literals, every resolved address must be public. The HTML sitemap crawl is not built: the pinned snapshot covers the corpus (YAGNI); `check_url` is the gate a crawler must call | S04-T01 | `ingest.py::check_url` | 7 refused URLs + 1 accepted | Done (crawler not built) |
| Retrieval: SQLite FTS5 (porter, unicode61), each word quoted (no FTS syntax from users), question words dropped (dev tuning, R@5 0.53 → 0.68 for BM25); fastembed `BAAI/bge-small-en-v1.5` vectors cached in `.cache/` per corpus hash (527 → 524 passages after front matter parsing; cold build about 40 s on an M4); RRF k = 60 | S04-T02 | `voicecore/answer/index.py` | `test_answer_ingest.py`, `reports/retrieval_*.json` | Done |
| Tool decision: retrieval runs before the LLM (one round trip per turn, about 600 ms saved against a model-issued tool call); `docs_search()` is the same retrieval as a function. `Grounding` releases a sentence only with a valid `[n]` for a retrieved passage, strips invented numbers and model-written URLs, holds uncited sentences, and turns an uncited answer into the fixed refusal | S04-T03 | `voicecore/answer/engine.py` | `test_answer_engine.py` | Done |
| One engine for text and voice: `Session(answer=engine.stream)` for both; `answer.sources` carries `{n, id, title, url}` from the index; speech goes through `speechify` (no `[n]`, no URLs) | S04-T04 | `engine.py`, `runtime/session.py`, `server.py` | parity test | Done |
| Hardening after the first adversarial run: flagged passages are never quoted; only the pinned official snapshot is quoted (labels alone did not stop gpt-4.1-nano repeating contradicting pages). A fresh adversarial set was written and committed (`8646c71`) before the fixed engine was run | S04-T05 | `engine.py::retrieve` | `reports/docs_eval.md` | Done |

## Execution record

| Task ID | Status | Output paths | Test command/results | Blocker |
|---|---|---|---|---|
| S04-T01 | Done 2026-10-30 | `voicecore/answer/ingest.py`, `fixtures/docs/adversarial*/` | ingest twice → identical ids and hashes (524 passages); canonical URL with fragment; SSRF refusals for 127.0.0.1, 10.1.2.3, 169.254.169.254, file://, unlisted host, http, localhost; injection text kept and flagged; stale and unauthorized pages skipped | — |
| S04-T02 | Done 2026-10-30 | `voicecore/answer/index.py`, `harness/retrieval_eval.py`, `reports/retrieval_dev.json`, `reports/retrieval_holdout.json` | FTS5 present; `uv lock` → "Creating the lockfile" first (fused); `uv.lock --frozen` does not raise; RRF example [B, A]; paraphrase in dense top 3. Fused dev R@5 0.79 / MRR 0.649; holdout 1.00 / 0.886 | — |
| S04-T03 | Done 2026-10-30 | `voicecore/answer/engine.py` | invented citation [9] rejected; model URL removed; uncited answer → refusal; refusal has no sources; engine streams grounded text then `answer.sources` with docs URLs only | — |
| S04-T04 | Done 2026-10-30 | `engine.py`, `server.py` | same question as text and as voice (mock STT) → same source ids and text; TTS text has no `[`; voice e2e (Playwright) still passes with the engine in the server | — |
| S04-T05 | Done 2026-10-30 (live, text only) | `harness/answer_eval.py`, `reports/docs_eval.{md,json}`, `docs_eval_v1.json`, `docs_eval_v2_labels.json` | Holdout: refusal accuracy 15/15, citations supported 15/15, must_contain 10/11. Adversarial v1 10/15 → v3 13/15 (0 leaked claims); fresh set 6/6 (contradiction policy chosen after its v2 run: unbiased contradiction 1/2). Cost $0.011 | — |

## Source and artifact change record

| Consumed artifact | Revision or hash | Affected task(s) | Revalidation decision |
|---|---|---|---|
| `fixtures/docs/answer_key.json` | v1 (S00-T03) | S04-T02, T05 | consumed unchanged |
| `fixtures/docs/uv` | tag 0.13.6, `329bf94` | all | front matter now parsed (3 passages fewer) |
| fastembed / bge-small-en-v1.5 | fastembed 0.9.1 | S04-T02 | model cached in `.cache/fastembed` (CI cache added) |

## Handoff

Update the registers with real paths and verification. The next step must read the latest output contracts, selected provider configurations and actual evidence. Any change to a prior artifact requires impact review and focused revalidation; the next step must not hard-code an old value copied from this document.
