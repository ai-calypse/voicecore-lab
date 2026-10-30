# Step 08: Portfolio Release

**Status:** Complete (2026-10-30) for T01–T04. Going public waits on the user: hosting choice, the security review findings, and the decision to make the repository public.  
**Estimated engineering effort:** 18 hours.  
**Task owner:** Implementation agent; user confirms external paid credentials.  

## Purpose and scope

Package credible proof of engineering depth for interviews and open-source review. Focus on ownership and evidence, not cosmetic product polish. Follow the global project non-goals in [master plan](./voicecore_lab_career_aligned_plan.md#explicit-non-goals).

## Step-specific implementation-agent prompt

> Act as a senior real-time voice software engineer. Read this step, the canonical [plan](./voicecore_lab_career_aligned_plan.md), [process](./README.md#source-of-truth-and-change-detection), and referenced previous step outputs. Inspect the existing code and prior execution records. Implement all remaining tasks in dependency order, verify with real commands and tests, record actual evidence/paths, and stop at this step's exit gate. Never invent pass results, provider support, latency numbers or source files.

## Required reading and prerequisites

- [Master architecture and contracts](./voicecore_lab_career_aligned_plan.md#system-architecture)
- [Previous step](./step_07_media_internals_and_optional_telephony.md) and its actual outputs, not merely planned files.
- Exact upstream code artifacts and ADRs named in the tasks below; if missing, record blocker and do independent preparations only.

## Decision ownership

This step owns the task-specific implementation choices, contracts and test evidence described below. It inherits the public goals, constraints, budget philosophy, evaluation thresholds and overall stack from the master plan. Do not silently change cross-step contracts. If needed, update the responsible upstream ADR/document and mark affected work for review.

## Phases and specific tasks

### S08-T01 — Embed and playground

**Outcome / implementation:** Create single JS snippet voice/text widget, text fallback, docs citations, permission UX, session cleanup.  
**Inputs:** This document, [master](./voicecore_lab_career_aligned_plan.md), current upstream records and working code.  
**Dependencies:** None beyond prerequisites.  
**Expected artifacts:** `packages/web-sdk and apps/demo` (planned; actual paths may be selected in owner register).  
**Edge/failure concerns:** Handle invalid input, task cancellation, empty data and path/session lifecycle where applicable; explicitly mark any scenario that is genuinely not applicable.  
**Acceptance test:** Unrelated plain HTML page can embed; voice/text and revoked mic all work.  

### S08-T02 — Reproducible deployment

**Outcome / implementation:** Compose local stack, dev/test instructions, secrets templates, CI status and bounded demo deployment.  
**Inputs:** This document, [master](./voicecore_lab_career_aligned_plan.md), current upstream records and working code.  
**Dependencies:** S08-T01.  
**Expected artifacts:** `docker-compose.yml, .env.example, README.md` (planned; actual paths may be selected in owner register).  
**Edge/failure concerns:** Handle invalid input, task cancellation, empty data and path/session lifecycle where applicable; explicitly mark any scenario that is genuinely not applicable.  
**Acceptance test:** New contributor can reproduce without undisclosed setup and without exposed credentials.  

### S08-T03 — Engineering portfolio

**Outcome / implementation:** Write design decisions, tradeoffs, methodology, failure postmortems, benchmark chart, README video script.  
**Inputs:** This document, [master](./voicecore_lab_career_aligned_plan.md), current upstream records and working code.  
**Dependencies:** S08-T02.  
**Expected artifacts:** `docs/portfolio_story.md; docs/architecture.md` (planned; actual paths may be selected in owner register).  
**Edge/failure concerns:** Handle invalid input, task cancellation, empty data and path/session lifecycle where applicable; explicitly mark any scenario that is genuinely not applicable.  
**Acceptance test:** Every result labeled measured/target; screenshots map to real system.  

### S08-T04 — Requirements alignment verification

**Outcome / implementation:** Re-check the requirements matrix against the code paths and pick 2 PR ideas for relevant open source projects (matrix and notes kept outside the public repository).  
**Inputs:** This document, [master](./voicecore_lab_career_aligned_plan.md), current upstream records and working code.  
**Dependencies:** S08-T03.  
**Expected artifacts:** requirements matrix, kept private (planned; actual paths may be selected in owner register).  
**Edge/failure concerns:** Handle invalid input, task cancellation, empty data and path/session lifecycle where applicable; explicitly mark any scenario that is genuinely not applicable.  
**Acceptance test:** No invented metrics, no misrepresentation of external contributions.  

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
| Widget = one classic script (`voicecore.js`, 18 KB / 7 KB gzip, Vite library build) reading `data-endpoint`; Shadow DOM so host CSS selectors cannot reach it, base font set on its own elements because inheritance crosses the boundary (found with a hostile test page); session token from the gateway only | S08-T01 | `apps/demo/src/widget.ts`, `widget.css`, `vite.widget.config.ts`, `public/embed-test.html` | Playwright `widget.spec.ts` (4) | Done |
| Look: launcher pill + orb and an open panel with a central orb and mic, modelled on the interaction in `docs/assets/*_reference.png` with an original palette, copy and icons (no ElevenLabs branding); `ui-taste` skill, no image tool authorised; inspected at 1280×760 light/dark and 390×844 | S08-T01 | `widget.css` | screenshots in the session log | Done |
| Deployment: 3 images (distroless Go gateway; Python orchestrator with the embedding model and docs vectors baked in, non-root, batch size 16 after an out-of-memory at build; nginx demo), ports bound to 127.0.0.1, mock providers by default, ledger mounted for live mode | S08-T02 | `docker-compose.yml`, `services/*/Dockerfile`, `apps/demo/Dockerfile`, `.dockerignore`, `.env.example` | CI `compose` job | Done |
| `harness/smoke.py`: token → WebSocket → typed question → cited answer; used in the README and CI | S08-T02 | `harness/smoke.py` | CI run 40994096269 | Done |
| Hosting a public demo is not done: it needs the user's choice of host and a decision on a capped live pool (the plan keeps it on mocks) | S08-T02 | — | — | Waits on user |
| Portfolio documents with every number labelled and linked to its report; chart rendered for light and dark GitHub themes (`dataviz` skill, palette validated) | S08-T03 | `docs/architecture.md`, `docs/portfolio_story.md`, `docs/writeups/01..03`, `docs/video_script.md`, `harness/latency_chart.py`, `reports/latency_chart_{light,dark}.png` | — | Done |
| Requirements re-check (matrix and notes kept outside the public repository) | S08-T04 | private | — | Done |

## Execution record

| Task ID | Status | Output paths | Test command/results | Blocker |
|---|---|---|---|---|
| S08-T01 | Done 2026-10-30 | `apps/demo/src/widget.*`, `apps/demo/index.html` | Playwright on a plain page with hostile CSS: embed + isolation, typed question → cited answer with docs links, spoken question → transcript, answer, playback; blocked mic → message, mic disabled, text answers. Same widget verified against the compose stack | — |
| S08-T02 | Done 2026-10-30 (local + CI); public hosting open | `docker-compose.yml`, Dockerfiles, `.env.example`, `README.md`, `harness/smoke.py` | Local `docker compose up --build` → smoke exit 0 (cited answer, 2 docs URLs), widget + lab page in Chromium; CI `compose` job from a clean checkout passed (run 40994096269) | Host and live-pool decision: user |
| S08-T03 | Done 2026-10-30 | `docs/architecture.md`, `docs/portfolio_story.md`, `docs/writeups/`, `docs/video_script.md`, `reports/latency_chart_*.png` | every number links to a report with its label; video shots map to real screens | Video not recorded (needs the user) |
| S08-T04 | Done 2026-10-30 | requirements matrix and notes (kept private) | every proof row has a path, test and evidence with an honest status; 2 OSS ideas marked not submitted | — |

## Source and artifact change record

| Consumed artifact | Revision or hash | Affected task(s) | Revalidation decision |
|---|---|---|---|
| Security review before going public (independent agent, whole repo, 2026-10-30): no secrets in files or history; XSS, token HMAC, origin checks and the budget guard's reservations were fine. Fixed: (high) `text.input` was not type-checked, so content-part lists could reach the LLM and history and be under-billed; now a ≤ 500-character string in the gateway (1008) and the runtime, and the LLM pre-check estimates the actual prompt. (medium) Unlimited sessions could lock or drain the pools: 50 total / 4 per IP (1013), 10 tokens per minute per IP, 15 min maximum age, TTS credits reserved on first speech. (medium) Flooding: mic frames rate-limited to real time (2 s burst), `text.input` 1/s (burst 5), ≤ 256 queued events. (low) Host allow-list against DNS rebinding (421), `ReadHeaderTimeout`; `check_url` rejects backslashes, userinfo and ports other than 443; unprivileged nginx; CI `permissions: contents: read`. A resume race found by the new tests was also fixed (fence before welcome). Not changed: `/debug/counters` stays public on the dev gateway; committed benchmark logs contain the local username in file paths | review 2026-10-30 | S01, S03, S04, S08 | `session/limits_test.go` (7), Python validation test, SSRF cases, compose smoke + 421 check |
| Code review (medium, `04206da..c48c722`, Steps 07–08): 10 findings, all fixed: widget close during connect left a live session; failed connect leaked AudioContexts; mic double-click orphaned a capture; citations carried into a reopened session; barge-in stop overwrote "Listening…"; compose ledger not writable on Linux in live mode (now `HOST_UID`/`HOST_GID`); RTP jitter not wrap-safe (new test); Pion PeerConnections never closed; widget loaded on the lab page; chart used a hard-coded value | review 2026-10-30 | S07-T01..T02, S08-T01..T03 | tests + e2e re-run |
| `docs/assets/voice_*_reference.png` | 2026-10-28 | S08-T01 | interaction pattern only, no branding copied |
| Reports from Steps 01–07 | as committed | S08-T03 | numbers copied with links, not retyped from memory |

## Handoff

Update the registers with real paths and verification. The next step must read the latest output contracts, selected provider configurations and actual evidence. Any change to a prior artifact requires impact review and focused revalidation; the next step must not hard-code an old value copied from this document.
