# VoiceCore Lab documents

VoiceCore Lab is an engineering portfolio project, **not a commercial SaaS**. Start with the [project README](../README.md).

## For readers

| Read | For |
|---|---|
| [Project tour](portfolio_story.md) | every area the project covers: the problem, what was built, the hard part, the proof |
| [Architecture](architecture.md) | how the parts fit, with diagrams of every flow |
| [Write-ups](writeups/) | three things that went wrong or forced a trade-off: [false barge-ins](writeups/01-false-barge-ins.md), [prompt injection](writeups/02-grounding-under-attack.md), [endpointing](writeups/03-endpointing-tradeoff.md) |
| [ADRs](adr/) | the decisions and the evidence behind them |
| [Media internals](media_internals.md), [telephony design](telephony_extension.md) | the audio path in depth; where a phone line would plug in |
| [Operations](ops/) | [runbooks](ops/runbooks.md), [monitoring](ops/monitoring.md), [targets](ops/slos.md), [incidents](ops/incidents.md), [deploy](ops/deploy.md), [data map](ops/data-map.md), [key rotation](ops/key-rotation.md) |
| [Diagrams](diagrams/) | the editable sources of every diagram |
| [Reports](../reports/) and [benchmarks](../benchmarks/) | every measured number, with the command that produced it |

## How the work was planned

The [master plan](voicecore_lab_career_aligned_plan.md) owns the scope, non-goals, targets and stack defaults. The build ran in ten steps, each with task ids, dependencies, evidence criteria and a register of what was actually done:

- [00. evidence and baselines](step_00_career_evidence_and_baselines.md) (12 h)
- [01. audio transport and SDK](step_01_audio_transport_and_sdk.md) (30 h)
- [02. voice activity and turn detection](step_02_voice_activity_and_turn_detection.md) (30 h)
- [03. streaming orchestrator](step_03_streaming_orchestrator.md) (38 h)
- [04. grounded docs agent](step_04_grounded_docs_agent.md) (25 h)
- [05. barge-in and recovery](step_05_barge_in_and_recovery.md) (28 h)
- [06. observability, evals and load](step_06_observability_evals_and_load.md) (40 h)
- [07. media internals and optional telephony](step_07_media_internals_and_optional_telephony.md) (35 h)
- [08. portfolio release](step_08_portfolio_release.md) (18 h)
- [09. production readiness](step_09_production_readiness.md) (about 110 h; plan: [PRODUCTION_PLAN.md](PRODUCTION_PLAN.md))

The test-first build plan for Steps 01–08 is [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md). Hours are planning estimates, not time logged. [EXECUTION_STATUS.md](../EXECUTION_STATUS.md) records what was done, with evidence.

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

A reviewer can trace each requirement to code ownership, deterministic tests, a live demo and raw measured evidence. A voice SDK wrapper alone is **not** sufficient.
