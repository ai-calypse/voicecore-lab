# Performance, load and endpointing (S06-T04, S06-T06)

**Date:** 2026-10-30 UTC. **Machine:** Apple M4, macOS 26.5.2; every process on one laptop, with providers over a residential network. **Metric definitions:** `harness/timeline.py` (`turn_breakdown`, nearest-rank `percentile`). **Total** = labelled end of the user's speech → first agent sample rendered by the client.

## Fake providers (`fake-provider`, n = 216)

Command: `uv run python harness/bench.py` → [`perf_fake.json`](perf_fake.json).

- **Runs:** in-process on fake time, with real Silero VAD, floor and runtime.
- **Mocks:** STT final on `Finalize`, LLM first token 200 ms, TTS first audio 150 ms.
- **Grid:** 12 dev speech clips × one-way delay 0 / 20 / 50 ms × clean or 15 dB pink noise × 3 seeds.

| | p50 | p95 | p99 |
|---|---:|---:|---:|
| Total | 1,320 ms | 1,440 ms | 1,480 ms |
| Endpoint delay | 860 ms | 980 ms | 980 ms |

- **Reliability:** 216 / 216 answered, 0 early cutoffs, 0 STT queue drops.
- **Network:** median total 1,260 / 1,300 / 1,360 ms at 0 / 20 / 50 ms one-way delay.
- **Interpretation:** with fake providers, the endpoint (800 ms of silence plus about 60 ms of VAD lag) is two thirds of the total.

## Live providers (`live-provider`, n = 30)

Command: `uv run python harness/runner/wss.py --providers live --policy fixed|asr_assisted --sequential --tail 10 --clips <15 dev docs questions>`, then `harness/latency.py`.

- **Path:** headless SDK client → Go gateway → orchestrator → Deepgram nova-3 (with keyterms), gpt-4.1-nano via OpenRouter, Cartesia sonic-3.6.
- **Input:** 15 dev docs questions spoken by Aura, the same 15 under each policy.

| Policy (ADR 0002) | Turns answered in one piece | Total p50 / p95 | Speech end → LLM request p50 / max | LLM first token p50 / p95 | TTS first audio p50 | Residual p50 |
|---|---:|---:|---:|---:|---:|---:|
| **fixed 800 ms** (`wss_live_fixed_20261030T020448Z`) | **15 / 15** | 2,317 / 3,102 ms | **862 / 902 ms** | 939 / 1,758 ms | 456 ms | 13 ms |
| asr_assisted (`wss_live_asr_assisted_20261030T020917Z`) | 12 / 15 | 2,259 / 6,817 ms | 523 / 572 ms | 1,289 / 5,856 ms | 406 ms | 16 ms |

- **asr_assisted decides about 340 ms sooner,** but **3 of 15 questions were cut in half live.** Deepgram finalised and punctuated at a pause inside the question, for example "When moving from pip." followed by "How do I import my requirements…". This confirms the simulated result, so ADR 0002 keeps fixed 800 ms.
- **The total is not a fair policy comparison.** OpenRouter's first token was slower during the asr_assisted batch (p95 5.9 s), so the policy is compared on speech end → LLM request instead. That uses the derived client↔orchestrator offset and is measured to about 1 ms.
- **The LLM's first token is the biggest live cost after endpointing.** Its median ranges from 0.8 s to 1.3 s between batches, with p95 spikes up to 5.9 s through OpenRouter.
- **STT keyterms fixed "uv".** With `uv`, `uvx`, `uv sync` and similar as keyterms, every question in this run that names uv was transcribed with "uv". In S03-T06, 5 of 10 had been misheard as "of", "OV", and so on.
- **Cost per live turn** (ledger, 30 sessions): STT $0.00083, LLM $0.00013, TTS 138 Cartesia credits.

## Load

### Mock providers through the real stack

Command: `uv run python harness/runner/wss.py --clips dev_single_02 --parallel N --tail 8`. Each client is a headless Node process on the same laptop as the gateway and orchestrator.

| Concurrent sessions | Completed | Total p50 / p95 | Residual p95 | Gateway drops / gaps |
|---:|---:|---:|---:|---:|
| 1 | 1 / 1 | 1,301 / 1,301 ms | 3 ms | 0 / 0 |
| 5 | 5 / 5 | 1,318 / 1,320 ms | 20 ms | 0 / 0 |
| 20 | 20 / 20 | 1,296 / 1,299 ms | 19 ms | 0 / 0 |
| 40 | 40 / 40 | 1,296 / 1,305 ms | 21 ms | 0 / 0 |

At 40 sessions the orchestrator runs 40 Silero VADs on one event loop, which is 2,000 frames/s. Latency did not move. CPU was not profiled, so the ceiling is unknown. A `ponytail:` note in `server.py` marks where VAD would move to a thread.

### Live

Two concurrent sessions (`wss_live_fixed_20261030T022346Z`) both completed: totals 2,183 and 3,020 ms, no gateway drops. 2 is the lowest Cartesia TTS concurrency tier (Free plan). Higher live concurrency was not run (budget and plan limit).

## CI regression gate

`harness/gate.py` with [`harness/thresholds.json`](../harness/thresholds.json) runs in `.github/workflows/evals.yml` on every push:

- **Scenarios:** 12 dev turns, 3 interrupts and 2 echo-only clips, in-process on fake time.
- **Thresholds:** latencies may grow by at most 100 ms over the measurement; counts may not get worse.

**Proof:** branch `ci-gate-proof` adds 200 ms to the mock LLM's first token. Locally the gate reports total p50 1,460 > 1,360 and p95 1,580 > 1,480, and the `evals` workflow failed on that branch ([run 40991626127](https://github.com/ai-calypse/voicecore-lab/actions/runs/40991626127)). On main it passes.
