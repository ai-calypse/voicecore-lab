# Latency breakdown (S03-T06)

**Date:** 2026-10-30 UTC. **Label:** `live-provider`, n = 10 turns. Small sample: medians and nearest-rank p95 only, not production rates.
**Raw:** [`benchmarks/raw/wss_live_20261030T010848Z/`](../benchmarks/raw/wss_live_20261030T010848Z/) (client logs, orchestrator traces, gateway counters, `latency.json`).
**Command:** `uv run python harness/runner/wss.py --providers live --sequential --tail 10 --clips dev_docs_question_q01 … q16`, then `uv run python harness/latency.py <run>`.

## Setup

- **Path:** headless SDK client (Node 24, real `VoiceClient` and `Playout`) → Go gateway → Python orchestrator, all on one Apple M4 laptop (macOS 26.5.2), residential network to the providers.
- **Providers:** Deepgram nova-3 streaming STT, `Finalize` sent at our endpoint; `openai/gpt-4.1-nano` via OpenRouter (temperature 0, `max_tokens` 80); Cartesia `sonic-3.6` (voice "Daniel", one context per generation).
- **Turn-taking:** Silero VAD v6.2.3 with the ADR 0002 default (fixed 800 ms).
- **Input:** 10 dev docs questions spoken by Deepgram Aura `aura-2-apollo-en` (local-only clips). The mic is paced at 20 ms and a frame leaves when its last sample is captured.
- **Not in this run:** the answer engine (Step 04 adds retrieval), so these answers are ungrounded.

## Where the time goes

| Stage | How it is measured | p50 | p95 |
|---|---|---:|---:|
| **Total: user stops speaking → first agent sample rendered** | client clock: labelled turn end → `playout.started` | **2,073 ms** | 2,472 ms |
| Endpoint (turn-taking) | client clock: turn end → end of the frame that triggered the endpoint | 860 ms | 900 ms |
| STT settle | orchestrator clock: endpoint → transcript ready (`Finalize` already returned it) | 0.6 ms | 0.9 ms |
| LLM time to first token | orchestrator clock: request → first token (OpenRouter → OpenAI, public internet) | 595 ms | 1,106 ms |
| TTS first audio | orchestrator clock: first token → first Cartesia audio. Includes waiting for the first full sentence | 572 ms | 776 ms |
| Residual | derived: total − the stages above = uplink + downlink + playout start | 16 ms | 22 ms |

The per-turn rows are in `latency.json`. The client and orchestrator clocks are never subtracted from each other. The endpoint is placed on the client clock through the `capture_us` of the mic frame that triggered it (SPEC section 5), so only the residual is derived.

## Against the hosted baseline

| | VoiceCore (this run) | Deepgram Voice Agent rerun `20261030T011208Z-46df14` |
|---|---:|---:|
| Speech end → first agent audio, median | 2,073 ms (n = 10, rendered) | 972 ms (n = 3, frame received) |
| Turns completed | 10 / 10 | 4 / 4 (the earlier `FAILED_TO_START_LISTENING` did not recur) |

These are **not matched conditions**:
- The baseline uses macOS `say` fixtures, `gpt-4o-mini` inside Deepgram's network, Deepgram's own endpointing, and stops at the first frame received.
- VoiceCore stops at the first sample rendered, which adds at most 20 ms.

Even so, the gap of about 1.1 s is real. The breakdown shows where it comes from:

1. **Endpointing, 860 ms.** The fixed 800 ms silence of ADR 0002 accounts for the largest part. The simulated `asr_assisted` policy ends turns about 500 ms sooner, but it cut mid-sentence pauses. Step 06 re-measures it with these live Deepgram finals.
2. **LLM first token, 595 ms.** There is an extra hop through OpenRouter and the model starts cold on each request. A direct provider connection or prompt caching would cut this, at the cost of the plan's provider choice.
3. **TTS first audio, 572 ms.** The chunker waits for a whole first sentence before calling Cartesia. Splitting the first chunk at a clause would start audio earlier.

## Quality notes from the same run (not latency)

- **STT hears "uv" wrongly.** Deepgram transcribed "uv" as "of", "OV", "u v" and "OfSync" ("uv sync") in 5 of 10 questions. nova-3 supports `keyterm` prompting, so the STT adapter should boost `uv`, `uvx` and `uv sync` (Step 04/06).
- **The answers are wrong without the docs.** For example, "pip install uv", "uv new" and an Ubuntu LTS answer. That is expected before the answer engine exists; Step 04 grounds every answer in the uv docs snapshot.
- 2 of 10 answers were still playing when the 10 s tail ended, so their `playout.stopped` is missing from the logs. This is not a fault.

## Spend

- **This run:** $0.022 and 1,141 Cartesia credits.
- **Baseline rerun:** $0.075.
- **Pools after Step 03:** usd **$0.706** of $5.00, Cartesia **1,279** of 16,000 credits.
- **OpenRouter check:** its own `/api/v1/key` usage rose by about $0.0003 over this work. The ledger records $0.0002 of LLM settles. Both are tiny, and the ledger's reservations cover the gap.
