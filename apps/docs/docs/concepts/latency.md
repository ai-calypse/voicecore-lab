---
title: Latency in a voice agent
sidebar_label: Latency
description: How this repository measures voice latency from the end of the user's speech to the first rendered agent sample, where the time goes, and how the tuned numbers compare with a hosted baseline.
---

## The latency metric this repository reports

The headline number is the time from the labelled end of the user's speech to the first agent sample rendered by the client. It is the wait the user hears after they stop talking. The test clips have exact turn-end labels, so the speech end is known instead of guessed from a VAD. The client logs when its microphone started, so the speech end is that time plus the labelled offset. The client's `playout.started` event gives the render time on the same clock. The metric is defined once, in `harness/timeline.py` (`turn_breakdown`), and every report uses that definition. When a turn had more than one generation, for example after a continuation merge, it is measured to the generation that actually played. Percentiles are nearest rank.

## How each stage of a turn is measured

The total is split into stages, each measured on one clock. The client clock and the orchestrator clock are never subtracted from each other. The endpoint is placed on the client clock through the capture time of the mic frame that triggered it, so only the residual is derived. Because of that, a stage breakdown stays honest even though the processes run on separate clocks.

| Stage | From and to | Clock |
|---|---|---|
| Total | labelled speech end → first agent sample rendered | client |
| Endpoint delay (turn end detected) | speech end → end of the mic frame on which the floor decided | client |
| STT settle | endpoint → transcript ready | orchestrator |
| LLM first token | LLM request → first token | orchestrator |
| TTS first audio | first token → first TTS audio, including the wait for the first full sentence | orchestrator |
| Residual (transport and playout) | total minus the stages above: uplink, downlink and playout start | derived |

## Stage breakdown before and after tuning

These runs used the same 15 dev docs questions, spoken by a Deepgram Aura voice. The full stack ran: headless SDK client, Go gateway, orchestrator, then Deepgram, OpenRouter and, for speech, Cartesia sonic-3.6, except in the Deepgram Aura-2 row. Every process ran on one Apple M4 laptop, with providers over a residential network. All rows are live; values are p50 unless a p95 is shown. The hard-audio row uses noisy (10 and 5 dB), slowed (0.8×) and paused (600 ms mid-sentence) LibriSpeech clips. The Deepgram Aura-2 row is a smaller run on 6 of the questions. The assistant answered them from this docs site, so most replies were short "not in these docs" answers. The stage medians do not add up to the total median, because each median can come from a different turn.

| Run | Total p50 / p95 | Turn end detected | LLM first token p50 / p95 | TTS first audio | Transport and playout |
|---|---:|---:|---:|---:|---:|
| Before: fixed 800 ms, gpt-4.1-nano (n = 15) | 2,317 / 3,102 ms | 861 ms | 939 / 1,758 ms | 456 ms | 13 ms |
| After: eager endpoint, gpt-oss-120b on Cerebras (n = 15) | 841 / 1,520 ms | 340 ms | 340 / 1,013 ms | 145 ms | 26 ms |
| After, hard audio (n = 12) | 841 / 1,218 ms | 340 ms | 366 / 704 ms | 134 ms | 21 ms |
| After, Deepgram Aura-2 speech instead of Cartesia (n = 6) | 802 / 1,059 ms | 300 ms | 411 / 593 ms | 115 ms | 23 ms |

## Where the time went before tuning

Before tuning, the live turn took p50 2,317 ms (live, n = 15), and three stages explain nearly all of it. The endpoint took p50 861 ms (live, n = 15), the largest single slice. It is the fixed 800 ms of silence plus Silero VAD's lag of about three 20 ms frames in reporting the end of speech. The LLM's first token took p50 939 ms (live, n = 15), through an extra hop via OpenRouter to `gpt-4.1-nano`. TTS first audio took p50 456 ms (live, n = 15). It included waiting for the first full sentence and opening the Cartesia connection on the first answer. Transport and playout start were only p50 13 ms (live, n = 15). On a single laptop, the network between the processes is not where voice latency goes.

## What each tuning change bought

Each change targeted one stage, and each stage was re-measured live on the same 15 questions (live, n = 15, p50). The LLM change was picked from a text-only trial with the real grounded prompt. There, first-token p50 was 300 ms for `gpt-oss-120b` on Cerebras against 574 ms for `gpt-4.1-nano` (live, text only, n = 6 per config). The reasoning tokens of `gpt-oss-120b` count against `max_tokens`, so the answer limit went from 80 to 200 tokens.

| Change | Stage | Before → after (live p50, n = 15) |
|---|---|---:|
| `openai/gpt-oss-120b`, OpenRouter provider Cerebras first, reasoning effort low | LLM first token | 939 → 340 ms |
| One shared HTTP pool with 60 s keep-alive, and a free `/key` request at session start | LLM first token | part of the above |
| Cartesia WebSocket opened at session start, before the first answer | TTS first audio | 456 → 145 ms |
| Eager endpoint: Finalize at 200 ms of silence, end on a punctuated final, else after 800 ms | Turn end detected | 861 → 340 ms |
| Continuation merge for early cut-offs | none; it keeps eager's cut-offs from splitting a question | — |

## Where the remaining time goes

After tuning, with Cartesia speech, the turn is p50 841 ms (live, n = 15), and the endpoint and the LLM share most of it equally. Turn end detection is p50 340 ms and the LLM's first token is p50 340 ms (live, n = 15). TTS first audio is p50 145 ms with Cartesia, and transport and playout start are p50 26 ms (live, n = 15). With Deepgram Aura-2 speech, the default since 2026-10-30, TTS first audio was p50 115 ms and p95 162 ms, and the total p50 802 ms and p95 1,059 ms (live, n = 6). Most of the remaining endpoint wait is fixed by design. The eager policy hears 200 ms of VAD silence before it sends Finalize. Silero reports the end of speech about 60 ms late (offline fixtures, n = 12), and Deepgram's final arrives about 100 ms after Finalize (live STT, n = 37). Speculative LLM calls on partial transcripts could remove most of that wait at the cost of more LLM calls; that has not been tried. In the Cartesia run, 13 of 15 docs turns finished under 1,000 ms (live, n = 15).

## What p95 means with small samples

The p95 in these reports is a nearest-rank percentile: the smallest value with at least 95 % of the values at or below it. With 10, 12 or 15 turns, that rank is the last one, so the p95 is the slowest turn of the run. A p95 of 1,520 ms (live, n = 15) therefore describes one turn, not a stable tail. The reports call these samples small (6 to 37 per number) and say they rank configurations rather than predict production rates. There were no repeat runs at different times of day. LLM provider latency moved by about 2× between live batches before tuning, so check the p95 again before you quote it widely.

## Why the latency tail comes from the language model

The endpoint is bounded by policy, but the LLM's first token is not. With the eager policy, the slowest possible endpoint is the 800 ms silence fallback. That is what happened to q17, where no punctuated final arrived (live, n = 15). The LLM has no such bound. Before tuning, its first token was p50 939 ms but p95 1,758 ms (live, n = 15). In another batch through OpenRouter it reached p95 5,856 ms, and that batch's total p95 was 6,817 ms (live, n = 15). Its first-token median ranged from about 0.8 s to 1.3 s between batches. After tuning, the slowest docs turn was q21, whose first token took 1,013 ms (live, one turn of n = 15). The shipped adapter allows OpenRouter provider fallbacks, so a Cerebras outage makes turns slower instead of failing them.

## Comparison with the hosted Deepgram baseline

The hosted Deepgram Voice Agent measured a median of 972 ms from speech end to the first agent audio frame received (live, n = 3, min 957 ms, max 1,038 ms). The tuned cascade measured p50 841 ms to the first sample rendered (live, n = 15). Before tuning, the cascade was 2,073 ms (live p50, n = 10), a gap of about 1.1 s. The comparison is not matched. The baseline used macOS `say` fixtures, `gpt-4o-mini` inside Deepgram's network and Deepgram's own endpointing. It stopped at the first frame received, while this repository stops at the first sample rendered. The tuning report puts rendering about 10 to 26 ms after receipt (live). The baseline has only 3 voice turns, run once. Read the comparison as "close to the hosted agent", not as faster than it.

## Mock numbers compared with live numbers

Mock runs (`fake-provider` in the reports) use real Silero VAD, the real floor and the real runtime on fake time. The STT returns its final on Finalize, the LLM's first token takes 200 ms and TTS first audio takes 150 ms. Over 12 clips, 3 network delays, clean or noisy audio and 3 seeds, the total was p50 1,320, p95 1,440 and p99 1,480 ms (mock, n = 216). The endpoint alone was p50 860 ms (mock, n = 216), because mock mode keeps the fixed 800 ms policy. Through the real stack, 1 to 40 concurrent sessions all stayed between p50 1,296 and 1,318 ms (mock, runs of 1, 5, 20 and 40 sessions). Mock numbers check the code path and catch regressions: the CI gate fails when a latency grows more than 100 ms over its recorded value. They say nothing about provider latency.

## How to reproduce a latency run

A live run starts the gateway and the orchestrator, plays labelled clips through headless SDK clients and writes traces and client logs to a run directory. A second command computes the breakdown with `harness/timeline.py`. Live runs spend real money against the project budget. The mock benchmark runs in-process on fake time and costs nothing. See [Measure latency](../guides/measure-latency.md) for the full procedure and [Tune latency](../guides/tune-latency.md) for the levers.

```bash
# live: full stack, sequential turns, 8 s tail after each clip
uv run python harness/runner/wss.py --providers live --sequential --tail 8 --clips <ids>
uv run python harness/latency.py <run dir>

# mock: in-process, fake time, real VAD
uv run python harness/bench.py
```
