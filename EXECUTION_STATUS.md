# VoiceCore Lab — Execution Status

**Status as of 2026-10-30:** Steps 00–03 complete (open items listed per row); Step 04 in progress. This file is a live execution register for the implementing agent.

Do not mark a step Complete until task-level actual evidence, objective tests and handoff checks are recorded in the corresponding step doc. Track fake and real provider results separately.

| Step | Status | Estimated hours (not time logged) | Verified outputs | Blocker / next action |
|---|---|---:|---|---|
| [00](docs/step_00_career_evidence_and_baselines.md) | Complete | 12 | S00-T01 matrix; S00-T02 baseline (live); S00-T03 fixtures; S00-T04 ADR 0001 | Open: intermittent `FAILED_TO_START_LISTENING` (3/7 sessions), investigated before Step 03 adapters |
| [01](docs/step_01_audio_transport_and_sdk.md) | Complete except S01-T05 loss profile (blocked) | 30 | Protocol + 3 codecs, browser capture, Go gateway, playout, tracer bullet, transport benchmark local + simulated (fake-provider) | Blocked: dummynet packet-loss profile needs the user (sudo) |
| [02](docs/step_02_voice_activity_and_turn_detection.md) | Complete except manual echo check | 30 | Silero + fixture VAD, floor (fixed/adaptive/asr), echo gate, evaluator, sweep + ADR 0002 (fixed 800 ms) | Open: manual speaker/AEC check (user) |
| [03](docs/step_03_streaming_orchestrator.md) | Complete | 38 | Provider contracts + 3 live adapters, generation runtime, server, in-process/WSS runners, chaos test, live latency breakdown (n = 10) | User: send the drafted Deepgram ticket (optional) |
| [04](docs/step_04_grounded_docs_agent.md) | Not started | 25 | None | Begin step 04 after prerequisites |
| [05](docs/step_05_barge_in_and_recovery.md) | Not started | 28 | None | Begin step 05 after prerequisites |
| [06](docs/step_06_observability_evals_and_load.md) | Not started | 40 | None | Begin step 06 after prerequisites |
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
| 2026-10-30 | S03-T01..T07 | Claude Code (Opus 5.5) | `voicecore/{providers,runtime}/`, `server.py`, `harness/{runner,latency.py,listen_repro.py}`, `reports/latency_breakdown.md` | `make test` (pytest 62, Go, vitest) + `make e2e` (3) pass; live contracts 7 passed; live latency n = 10 | usd pool $0.706, credits 1,279 |

## Handoff history

| Date (UTC) | Completed step | Approved handoff evidence | Next step permitted |
|---|---|---|---|
| 2026-10-29 | 00 | Registers filled; `make test` 16 passed; CI green on `eb7ee6e`; code-review findings fixed. User declined own-voice recordings and waived listen/read checks | 01 |
| 2026-10-30 | 01 (one blocked item) | Registers filled; `make test` + `make e2e` pass; CI green; code review (medium) 10 findings fixed. Open: S01-T05 loss profile needs sudo (user). User asked to complete all steps, so Step 02 proceeds; `/improve-codebase-architecture` and `/thermo-nuclear-code-quality-review` are user-run and not yet run | 02 |
| 2026-10-30 | 02 (manual echo check open) | Registers filled; tests pass; ADR 0002 | 03 |

**Planning update (2026-10-28):** Documented initial STT/VAD/LLM/TTS provider recommendations in the master plan. No live integration, verification, measurements, or step completion is implied.
