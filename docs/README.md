> **Master entry point:** [../MASTER_AGENT_GUIDE.md](../MASTER_AGENT_GUIDE.md). This page is the step-local process reference.

# VoiceCore Lab implementation documents

**Purpose:** career-oriented real-time voice AI engineering portfolio, **not a commercial SaaS**. This pack replaces the previous DocsVoice SaaS implementation pack. Read the [master plan](voicecore_lab_career_aligned_plan.md) first.

## Execution order

- [00. career evidence and baselines](step_00_career_evidence_and_baselines.md) — 12h
- [01. audio transport and sdk](step_01_audio_transport_and_sdk.md) — 30h
- [02. voice activity and turn detection](step_02_voice_activity_and_turn_detection.md) — 30h
- [03. streaming orchestrator](step_03_streaming_orchestrator.md) — 38h
- [04. grounded docs agent](step_04_grounded_docs_agent.md) — 25h
- [05. barge in and recovery](step_05_barge_in_and_recovery.md) — 28h
- [06. observability evals and load](step_06_observability_evals_and_load.md) — 40h
- [07. media internals and optional telephony](step_07_media_internals_and_optional_telephony.md) — 35h
- [08. portfolio release](step_08_portfolio_release.md) — 18h

## Source-of-truth and change detection

1. The master plan owns product intent, non-goals, total hours, evaluation targets and stack defaults.
2. A step document owns only the contracts and decisions explicitly assigned to that step. Later docs reference owner files and output registers rather than redefining mutable details.
3. Before a task, read fresh upstream docs and code artifacts, record their revision or hash, and check whether outputs changed.
4. At phase boundaries and before handoff, recheck upstream dependencies and mark affected completed tasks **Needs Review**. Revalidate impacted tests; do not redo unrelated work.
5. A step owner may revise selected assumptions only by changing the owning ADR, explaining the evidence, and documenting impacts to dependent docs and code.
6. A file link does not automatically propagate semantic changes. This is a **manual agent execution procedure** unless automation actually exists.
7. In the logs, label targets, simulated results and live measurements separately.

## Reusable agent instruction

> Read `docs/voicecore_lab_career_aligned_plan.md`, `docs/README.md` and the selected `docs/step_XX_*.md`. Read every referenced upstream decision/actual artifact. Inspect existing repo code, commit status and output registers. Implement **only** this step’s remaining authorized work with tests. Record modifications, commands, results, evidence, contract changes and blockers. Do not invent runs, latency figures, voice quality, provider integration or production stability. Update the owning document if decisions must change and revalidate downstream dependents. Stop at the specified handoff gate.

## What success means

A reviewer can trace career requirements → code ownership → deterministic tests → live demo → raw measured evidence. A voice SDK wrapper alone is **not** sufficient.
