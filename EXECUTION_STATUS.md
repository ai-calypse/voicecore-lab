# VoiceCore Lab — Execution Status

**Status as of 2026-10-30:** Steps 00–06 complete (open items listed per row); Step 07 in progress. This file is a live execution register for the implementing agent.

Do not mark a step Complete until task-level actual evidence, objective tests and handoff checks are recorded in the corresponding step doc. Track fake and real provider results separately.

| Step | Status | Estimated hours (not time logged) | Verified outputs | Blocker / next action |
|---|---|---:|---|---|
| [00](docs/step_00_career_evidence_and_baselines.md) | Complete | 12 | S00-T01 matrix; S00-T02 baseline (live); S00-T03 fixtures; S00-T04 ADR 0001 | Open: intermittent `FAILED_TO_START_LISTENING` (3/7 sessions), investigated before Step 03 adapters |
| [01](docs/step_01_audio_transport_and_sdk.md) | Complete except S01-T05 loss profile (blocked) | 30 | Protocol + 3 codecs, browser capture, Go gateway, playout, tracer bullet, transport benchmark local + simulated (fake-provider) | Blocked: dummynet packet-loss profile needs the user (sudo) |
| [02](docs/step_02_voice_activity_and_turn_detection.md) | Complete except manual echo check | 30 | Silero + fixture VAD, floor (fixed/adaptive/asr), echo gate, evaluator, sweep + ADR 0002 (fixed 800 ms) | Open: manual speaker/AEC check (user) |
| [03](docs/step_03_streaming_orchestrator.md) | Complete | 38 | Provider contracts + 3 live adapters, generation runtime, server, in-process/WSS runners, chaos test, live latency breakdown (n = 10) | User: send the drafted Deepgram ticket (optional) |
| [04](docs/step_04_grounded_docs_agent.md) | Complete | 25 | Ingestion + SSRF guard, hybrid retrieval, grounded answer engine shared by text and voice, live holdout + adversarial eval | — |
| [05](docs/step_05_barge_in_and_recovery.md) | Complete except manual loopback | 26 | Barge-in end to end, recovery rules, chaos reproducibility, fake + live interruption benchmark (kill gate passed) | Open: 5 manual acoustic runs (user). Cartesia credits over plan (6,446 used) |
| [06](docs/step_06_observability_evals_and_load.md) | Complete except manual answer audit | 40 | Trace timeline across 3 processes, lab panel, scenario simulator, fake + live perf, WER, load, CI eval gate | Open: 20-answer manual audit (user). Credits 10,877 / 16,000 |
| [07](docs/step_07_media_internals_and_optional_telephony.md) | Not started | 35 | None | Begin step 07 after prerequisites |
| [08](docs/step_08_portfolio_release.md) | Not started | 18 | None | Begin step 08 after prerequisites |

## Actual execution updates

| Date (UTC) | Step/task | Agent | Commit / paths | Test command and observed result | Blocker / decision |
|---|---|---|---|---|---|
| 2026-10-29 | S00-T01 | Claude Code (Opus 5.5) | No git repo; requirements matrix (kept private) | Per-role proof count and task-ID existence check: all roles pass, 0 unknown task IDs | — |
| 2026-10-29 | S00-T02 | Claude Code (Opus 5.5) | `harness/`, `benchmarks/` | Self-test ok. **Live provider** run `20261029T180728Z-a29514`: 8/12 turns (1 of 3 sessions failed setup); voice speech end → first agent audio frame median 1094.8 ms (n=6). 3 runs total, est. spend $0.525 of $2.00 cap | User approved paid use, $2 cap. First audio = frame received, not acoustic playback |
| 2026-10-29 | Build plan Step 0 (setup) | Claude Code (Opus 5.5) | `docs/IMPLEMENTATION_PLAN.md`, `GLOSSARY.md`, doc sync, `pyproject.toml` (uv workspace), `package.json` + `pnpm-workspace.yaml`, `services/realtime-gateway/go.mod`, `Makefile`, `.github/workflows/ci.yml`, `services/agent-core/voicecore/budget.py` | `make test` → 6 passed (`test_budget.py`); `uv run python harness/baseline_deepgram.py --self-test` → ok; usd pool total $0.525 | Keys for OpenRouter + Cartesia in `.env`; LLM `openai/gpt-4.1-nano` via OpenRouter ($0.10/$0.40 per M tokens, checked 2026-10-29); OpenRouter key has its own $1 limit. uizze skills `ui-taste` + `ios-design` installed at user scope and reviewed (Markdown only). Deviations from plan 0.6–0.8, all lazier: provider deps, Go/e2e CI jobs and `bench`/`fixtures` targets are added with their first use, not up front; harness has no own pyproject (root env + `pythonpath`). |
| 2026-10-29 | S00-T03, S00-T04 | Claude Code (Opus 5.5) | `fixtures/`, `harness/build_fixtures.py`, `harness/build_local_fixtures.py`, `harness/tests/test_fixtures.py`, `docs/adr/0001-engine-ownership.md` | `uv run pytest harness/tests` → 10 passed; 8/8 manifest mutations caught; byte-identical rebuild; code-review findings fixed | Aura clips local only (terms unconfirmed); usd pool $0.598 of $5.00 |
| 2026-10-30 | S01-T01..T07 | Claude Code (Opus 5.5) | `c5cc68e`..HEAD; `packages/`, `apps/demo/`, `services/realtime-gateway/`, `benchmarks/transport.md` | `make test` (Go 20 session + protocol, pytest 18, vitest 17) and `make e2e` (2 Playwright) pass | No sudo: shaped loss profile left to the user |
| 2026-10-30 | S02-T01..T05 | Claude Code (Opus 5.5) | `voicecore/turntaking/`, `harness/{timeline,turn_sweep}.py`, `reports/turn_policy*`, `docs/adr/0002-turn-policy.md` | `uv run pytest -m 'not live'` → 38 passed; sweep + holdout run once | Fixtures rebuilt at −23 dBFS for mixed clips |
| 2026-10-30 | S03-T01..T07 | Claude Code (Opus 5.5) | `voicecore/{providers,runtime}/`, `server.py`, `harness/{runner,latency.py,listen_repro.py}`, `reports/latency_breakdown.md` | `make test` (pytest 65, Go, vitest) + `make e2e` (3) pass; code review (02–03) 10 findings fixed; live contracts 7 passed; live latency n = 10 | usd pool $0.706, credits 1,279 |
| 2026-10-30 | S04-T01..T05 | Claude Code (Opus 5.5) | `voicecore/answer/`, `harness/{retrieval_eval,answer_eval}.py`, `fixtures/docs/adversarial*/`, `reports/docs_eval.md` | `make test` pass; live eval 3 runs ($0.011) | usd pool $0.718 |
| 2026-10-30 | S05-T01..T05 | Claude Code (Opus 5.5) | `voicecore/runtime/session.py`, `harness/{barge_bench,barge_live}.py`, `harness/runner/{inprocess,chaos}.py`, `reports/barge_in.md` | `make test` pass; live barge-in 8/8 silenced, 0/4 false | Credits 6,446 of 16,000 (Step 05 used ~4,950 vs 3,000 planned) |
| 2026-10-30 | S06-T01..T06 | Claude Code (Opus 5.5) | `harness/{timeline,session_timeline,bench,gate,wer_eval,lab_sample}.py`, `apps/demo/src/lab.*`, gateway trace, `reports/{perf,quality_eval}.md` | `make test` + `make e2e` (4) pass; evals gate pass on main, fail on proof branch | usd $0.82, credits 10,877 |

## Handoff history

| Date (UTC) | Completed step | Approved handoff evidence | Next step permitted |
|---|---|---|---|
| 2026-10-29 | 00 | Registers filled; `make test` 16 passed; CI green on `eb7ee6e`; code-review findings fixed. User declined own-voice recordings and waived listen/read checks | 01 |
| 2026-10-30 | 01 (one blocked item) | Registers filled; `make test` + `make e2e` pass; CI green; code review (medium) 10 findings fixed. Open: S01-T05 loss profile needs sudo (user). User asked to complete all steps, so Step 02 proceeds; `/improve-codebase-architecture` and `/thermo-nuclear-code-quality-review` are user-run and not yet run | 02 |
| 2026-10-30 | 02 (manual echo check open) | Registers filled; tests pass; ADR 0002; code review done together with Step 03 | 03 |
| 2026-10-30 | 03 | Registers filled; tests + e2e + live contracts pass; latency report; code review fixed | 04 |
| 2026-10-30 | 04 | Registers filled; tests + e2e pass; eval report | 05 |
| 2026-10-30 | 05 (manual loopback open) | Registers filled; tests pass; kill gate passed; barge-in report; code review (04–05) 10 findings fixed | 06 |
| 2026-10-30 | 06 (manual audit open) | Registers filled; tests, e2e and eval gate pass; reports | 07 |

**Planning update (2026-10-28):** Documented initial STT/VAD/LLM/TTS provider recommendations in the master plan. No live integration, verification, measurements, or step completion is implied.
