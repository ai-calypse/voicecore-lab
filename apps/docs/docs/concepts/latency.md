---
title: Latency in a voice agent
sidebar_label: Latency
description: VoiceCore's voice latency result (841 ms median from the end of your speech to the first sound of the answer), where that time goes, how tuning got there, and how it is measured.
---

## The result

**841 ms** is the median time from the moment you stop talking to the first sound of the answer.

| Measure | Result |
|---|---:|
| Median (p50) | **841 ms** |
| Slowest turn of the run (p95) | 1,520 ms |
| Turns under one second | 13 of 15 |

This was measured live: real providers over a home network, 15 spoken docs questions, every VoiceCore process on one Apple M4 laptop. The speech voice in that run was Cartesia. With Deepgram Aura-2, the default voice since 2026-10-30, a smaller run of 6 questions measured a median of 802 ms (live, n = 6). The hosted Deepgram Voice Agent measured 972 ms under different conditions; see [the comparison](#comparison-with-the-hosted-deepgram-baseline).

## Where the 841 ms goes

All numbers are medians from the same 15 live turns.

| Stage | Median | What happens in it |
|---|---:|---|
| Knowing you have finished speaking | 340 ms | The turn-taking floor waits for a short silence and a punctuated transcript |
| The language model's first word | 340 ms | `gpt-oss-120b` on Cerebras, through OpenRouter |
| The first audio from speech synthesis | 145 ms | The voice connection is already open when the answer starts |
| Network and playback | 26 ms | Gateway, browser and the start of audio output |

Each stage has its own median, so the four do not add up exactly to the total median.

Two stages take most of the time, in equal parts. Most of the end-of-turn wait is fixed by design. The eager policy waits for 200 ms of silence before it asks Deepgram for a final transcript. Silero VAD reports the end of speech about 60 ms late (offline fixtures, n = 12), and Deepgram's final arrives about 100 ms after it is asked for (live STT, n = 37). Calling the language model on partial transcripts could remove most of that wait, at the cost of more model calls; that has not been tried.

## How tuning took it from 2,317 ms to 841 ms

The first live build took a median of 2,317 ms on the same 15 questions. Three changes, each aimed at one stage, brought it to 841 ms.

| Stage | First build | Now | What changed |
|---|---:|---:|---|
| Knowing you have finished speaking | 861 ms | 340 ms | The eager endpoint replaced a fixed 800 ms of silence. It asks for a final transcript after 200 ms of silence and ends the turn on a punctuated final, or after 800 ms. |
| The language model's first word | 939 ms | 340 ms | `gpt-oss-120b` on Cerebras with low reasoning effort replaced `gpt-4.1-nano`, and the connection to OpenRouter now stays open for 60 s between turns instead of 5 s, so a turn no longer pays a fresh TLS handshake. |
| The first audio from speech synthesis | 456 ms | 145 ms | The voice connection opens when the session starts, not at the first answer. |
| Network and playback | 13 ms | 26 ms | Not tuned: on one laptop the network is not where the time goes. |
| **Total, median** | **2,317 ms** | **841 ms** | **2.8× faster** |

The model was chosen in a text-only trial with the real grounded prompt. Its first word came in a median of 300 ms on Cerebras, against 574 ms for `gpt-4.1-nano` (live, text only, 6 calls each). Its reasoning tokens count against the answer limit, so `max_tokens` went from 80 to 200.

The eager endpoint is faster because it sometimes ends a turn at a pause inside a question. The [continuation merge](./endpointing.md#how-the-continuation-merge-repairs-an-early-cut-off) repairs that: if you keep talking before the answer is audible, it cancels the answer and asks the whole question once. Latency is still measured from the end of the whole question.

## The same measurement on harder audio and another voice

| Run | Median | p95 |
|---|---:|---:|
| Docs questions, Cartesia voice (15 turns) | 841 ms | 1,520 ms |
| Hard audio: noisy at 10 and 5 dB, slowed to 0.8×, 600 ms pauses mid-sentence (12 turns) | 841 ms | 1,218 ms |
| Docs questions, Deepgram Aura-2 voice (6 turns) | 802 ms | 1,059 ms |

All three runs are live. The hard-audio clips are LibriSpeech readings rather than docs questions, so most answers were short refusals; they test the end-of-turn decision on difficult audio, and the stages are measured the same way. With Aura-2, the first audio from speech synthesis took a median of 115 ms.

## How the latency number is measured

The number is the time from the labelled end of your speech to the first agent sample the browser client renders: the wait you hear after you stop talking. The test clips have exact turn-end labels, so the end of speech is known instead of guessed from a VAD. The client logs when its microphone started, so the end of speech is that time plus the labelled offset. The client's `playout.started` event gives the render time on the same clock. The metric is defined once, in `harness/timeline.py` (`turn_breakdown`), and every report uses it. When a turn had more than one generation, for example after a continuation merge, it is measured to the generation that actually played.

Each stage is measured on one clock. The client clock and the orchestrator clock are never subtracted from each other. The end-of-turn decision is placed on the client clock through the capture time of the mic frame that triggered it, so only the network and playback slice is derived.

| Stage | From and to | Clock |
|---|---|---|
| Total | labelled end of speech → first agent sample rendered | client |
| Knowing you have finished speaking | end of speech → end of the mic frame on which the floor decided | client |
| Transcript ready | end-of-turn decision → transcript ready (under 1 ms, because Finalize already returned it) | orchestrator |
| The language model's first word | model request → first token | orchestrator |
| The first audio from speech synthesis | first token → first speech audio, including the wait for the first full sentence | orchestrator |
| Network and playback | total minus the stages above: uplink, downlink and playout start | derived |

## What p95 means with small samples

The p95 in these reports is a nearest-rank percentile: the smallest value with at least 95 % of the values at or below it. With 10 to 15 turns, that is the slowest turn of the run. A p95 of 1,520 ms (live, n = 15) therefore describes one turn, not a stable tail. Samples are small (6 to 37 per number), so they rank designs rather than predict production rates. There were no repeat runs at different times of day.

## Why the latency tail comes from the language model

The end-of-turn wait has a ceiling and the language model does not. With the eager policy, the slowest possible end-of-turn decision is the 800 ms silence fallback, which is what happened to q17 when no punctuated final arrived. The model has no such bound. In the slowest docs turn after tuning, q21, its first word took 1,013 ms. Before tuning, through `gpt-4.1-nano`, one batch reached a first-word p95 of 5,856 ms, and its median moved between about 0.8 s and 1.3 s from batch to batch. The shipped adapter allows OpenRouter to fall back to other providers, so a Cerebras outage makes turns slower instead of failing them.

## Comparison with the hosted Deepgram baseline

The hosted Deepgram Voice Agent measured a median of 972 ms from the end of speech to the first agent audio frame received (live, n = 3, min 957 ms, max 1,038 ms). VoiceCore measured 841 ms to the first sample rendered (live, n = 15).

The comparison is not matched. The baseline used macOS `say` fixtures, `gpt-4o-mini` inside Deepgram's network and Deepgram's own endpointing. It stopped at the first frame received, while VoiceCore stops at the first sample rendered, about 10 to 26 ms later. The baseline has only 3 voice turns, run once. Read it as "on par with the hosted agent", not as faster than it.

## Mock numbers compared with live numbers

Mock runs (`fake-provider` in the reports) use the real Silero VAD, the real floor and the real runtime on fake time, with scripted providers: the transcript is final on Finalize, the model's first word takes 200 ms and the first speech audio takes 150 ms. Mock mode keeps the fixed 800 ms end-of-turn policy, so its total is longer than live:

| Mock run | Median | p95 |
|---|---:|---:|
| 12 clips × 3 network delays × clean or noisy × 3 seeds (216 turns) | 1,320 ms | 1,440 ms |
| Real stack, 1 to 40 sessions at once | 1,296 to 1,318 ms | — |

Mock numbers check the code path and catch regressions: the CI gate fails when a latency grows more than 100 ms over its recorded value. They say nothing about provider latency.

## How to reproduce a latency run

A live run starts the gateway and the orchestrator, plays labelled clips through headless SDK clients and writes traces and client logs to a run directory. A second command computes the breakdown with `harness/timeline.py`. Live runs spend real money against the project budget. The mock benchmark runs in-process on fake time and costs nothing. See [Measure latency](../guides/measure-latency.md) for the full procedure and [Tune latency](../guides/tune-latency.md) for the levers.

```bash
# live: full stack, sequential turns, 8 s tail after each clip
uv run python harness/runner/wss.py --providers live --sequential --tail 8 --clips <ids>
uv run python harness/latency.py <run dir>

# mock: in-process, fake time, real VAD
uv run python harness/bench.py
```
