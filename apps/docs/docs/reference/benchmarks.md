---
title: Benchmarks
description: Every headline number VoiceCore has measured, for latency, endpointing, barge-in, transport, load, answer quality, word error rate and cost, each with its label, sample size, date and source report.
---

This page collects every headline number VoiceCore has measured, in one place. Each number carries its label, its sample size and the report it comes from, so you can check how it was measured. All runs are dated 2026-10-30 UTC, on one Apple M4 laptop (macOS 26.5.2), with live providers reached over a residential network.

## How to read these benchmark numbers

Every number on this page carries a label that says how it was measured:

- **live-provider:** the real stack with Deepgram, OpenRouter and Cartesia.
- **fake-provider:** mock providers with fixed delays. Everything else is real: Silero VAD, turn-taking, the generation runtime, and for the WSS runs the gateway and the SDK client.
- **simulated:** a user-space proxy that adds network delay and jitter.
- **measured offline:** no provider call at the time of measuring, for example retrieval ranking or a replay of recorded STT finals.

Percentiles are nearest-rank, as defined in `harness/timeline.py`. "Total" latency always means the labelled end of the user's speech to the first agent sample rendered by the client.

Samples are small, from 6 to 37 per number for the live runs. These numbers rank design choices; they are not production rates. Live provider latency moved by up to 2× between batches, so re-measure before you quote a p95.

## Voice turn latency with live providers

Total latency of a voice turn, end of the user's speech to the first agent sample rendered, through the full stack: headless SDK client, Go gateway, orchestrator and live providers.

| Configuration | Total p50 / p95 | n | Source |
|---|---:|---:|---|
| Current default: eager endpoint, gpt-oss-120b on Cerebras | 841 / 1,520 ms | 15 | `reports/latency_tuning.md` |
| Current default, hard audio (noisy, slow, mid-sentence pauses) | 841 / 1,218 ms | 12 | `reports/latency_tuning.md` |
| Before tuning: fixed 800 ms endpoint, gpt-4.1-nano | 2,317 / 3,102 ms | 15 | `reports/perf.md` |
| Before tuning: asr_assisted endpoint, gpt-4.1-nano | 2,259 / 6,817 ms | 15 | `reports/perf.md` |
| First breakdown, fixed 800 ms, gpt-4.1-nano, no retrieval | 2,073 / 2,472 ms | 10 | `reports/latency_breakdown.md` |
| Hosted Deepgram Voice Agent, for comparison | 972 ms median | 3 | `reports/latency_breakdown.md` |

The hosted baseline is measured to the first audio frame received, not rendered, with different fixtures and model, so it is not a matched comparison. In the current default run, 13 of 15 turns finished under 1,000 ms.

## Voice turn stages with live providers

Where the time goes in one live voice turn, per stage, before and after the latency tuning (live-provider, n = 15 each, the same 15 dev docs questions). The before run is `wss_live_fixed_20261030T020448Z`; the after run is `wss_live_eager_20261030T132949Z`. Values come from each run's `latency.json`, summarised in `reports/latency_tuning.md`.

| Stage | Before p50 / p95 | After p50 / p95 |
|---|---:|---:|
| Endpoint delay (detecting the end of the turn) | 860 / 900 ms | 340 / 820 ms |
| STT settle | 0.7 / 0.8 ms | 0.2 / 1.2 ms |
| LLM first token | 939 / 1,758 ms | 340 / 1,013 ms |
| TTS first audio | 456 / 531 ms | 145 / 186 ms |
| Residual: transport and playout start | 13 / 24 ms | 26 / 37 ms |
| Total | 2,317 / 3,102 ms | 841 / 1,520 ms |

The after p95 of the endpoint delay is high because one turn (q17) got no punctuated final and fell back to 800 ms of silence.

## Voice turn latency with mock providers

The same metric with mock providers: STT final on Finalize, LLM first token after 200 ms, TTS first audio after 150 ms. Endpointing is fixed 800 ms.

| Run | Total p50 / p95 / p99 | n | Source |
|---|---:|---:|---|
| In-process, fake time: 12 clips × 0, 20, 50 ms one-way delay × clean or 15 dB pink noise × 3 seeds | 1,320 / 1,440 / 1,480 ms | 216 | `reports/perf.md` |
| Endpoint delay in the same runs | 860 / 980 / 980 ms | 216 | `reports/perf.md` |
| CI gate scenario set, fake time | 1,260 / 1,380 ms (p50 / p95) | 12 | `harness/thresholds.json` |

In the 216-turn run, all 216 turns were answered, with 0 early cutoffs and 0 STT queue drops. The median total was 1,260, 1,300 and 1,360 ms at 0, 20 and 50 ms one-way delay. With mocks, the fixed endpoint is about two thirds of the total.

## LLM first token by model and provider

Text-only benchmark of time to the first answer token, with the real grounded prompt (about 1,200 input tokens), through OpenRouter with the provider pinned and no fallback (live-provider, n = 6 questions per configuration). Source: `reports/llm_ttft.json`, summarised in `reports/latency_tuning.md`.

| Configuration | First token p50 / max | First sentence p50 / max | Reasoning tokens |
|---|---:|---:|---:|
| gpt-4.1-nano | 574 / 2,061 ms | 791 / 2,691 ms | 0 |
| gpt-oss-120b, Cerebras, effort low | 300 / 514 ms | 314 / 538 ms | 31 to 77 |
| gpt-oss-120b, Groq, effort low | 451 / 744 ms | 505 / 792 ms | 19 to 57 |
| gpt-oss-120b, BaseTen, effort low | 508 / 579 ms | 579 / 718 ms | 0 reported |
| gpt-oss-20b, Groq, effort low | 514 / 754 ms | 538 / 768 ms | 14 to 77 |

gpt-oss-120b on Cerebras became the default. In live voice turns its first token measured p50 340 ms (n = 15). The benchmark streams text only, so its first-sentence column shows when TTS could start.

## Endpointing policies compared

How long each endpoint policy waits after the user stops speaking, and how often it ends a turn too early. Real Deepgram finals were recorded once for 37 dev clips (25 docs questions, 12 LibriSpeech clips), then replayed through each policy offline. Source: `reports/endpoint_study.json`, summarised in `reports/latency_tuning.md`.

| Policy (live finals, replayed, n = 37) | Delay p50 / p95 | Early cutoffs |
|---|---:|---:|
| fixed 300 ms | 360 / 440 ms | 14 |
| fixed 400 ms | 460 / 540 ms | 12 |
| fixed 500 ms | 560 / 640 ms | 6 |
| fixed 600 ms | 660 / 740 ms | 3 |
| fixed 800 ms | 860 / 940 ms | 0 |
| eager: punctuated final and 200 ms silence, else 800 ms | 400 / 540 ms | 5 |
| eager, else 600 ms | 400 / 540 ms | 7 |
| eager with 400 ms silence, else 800 ms | 460 / 540 ms | 4 |

Live with the eager default, the end of the turn was detected at p50 340 ms (n = 15). Early cutoffs were merged into one question in 6 of 27 live turns, before any of the early answer was audible.

## Barge-in, interrupt to silence

Interrupt-to-silence is the time from the labelled start of the user's speech to the client's `playout.stopped` with reason `cancel`, on one clock. A false barge-in is a cancel when nobody interrupted. Source: `reports/barge_in.md`.

| Run | Interrupts silenced | Interrupt to silence | False barge-ins |
|---|---:|---:|---:|
| Fake-provider, fake time, 0 ms one-way delay | 5 / 5 | p50 180, max 440 ms | |
| Fake-provider, 20 ms | 5 / 5 | p50 220, max 440 ms | |
| Fake-provider, 50 ms | 5 / 5 | p50 280, max 480 ms | 0 / 4 echo-only clips |
| Fake-provider, 100 ms | 5 / 5 | p50 380, max 560 ms | |
| Live-provider, after both fixes, two runs | 8 / 8 | p50 303, p95 1,364 ms | 0 / 4 echo-only scripts |

In the live run the client mixed its own playback into its mic at −15 dB to simulate a room. Each 20 ms of one-way delay adds about 40 ms. The live p95 is one clip, `dev_single_04`, whose short first word is followed by a pause. The CI gate holds the fake-time maximum at 540 ms.

## Transport overhead of the gateway

What the Go gateway adds to a round trip, measured on loopback with `cmd/wsload` and an echoing fake orchestrator: one 20 ms mic frame every 20 ms for 10 s per stream (fake-provider, local loopback). Source: `benchmarks/transport.md`.

| Profile | Streams | RTT p50 / p95 / p99 | Drops / gaps |
|---|---:|---:|---:|
| Direct to the fake orchestrator, no gateway | 1 | 0.24 / 0.37 / 0.43 ms | |
| Through the gateway | 1 | 0.43 / 0.60 / 0.69 ms | 0 / 0 |
| Through the gateway | 20 | 1.08 / 1.68 / 2.16 ms | 0 / 0 |
| Gateway + proxy 50 ± 20 ms each way (simulated) | 1 | 104.71 / 131.03 / 137.18 ms | 0 / 0 |
| Gateway + proxy 150 ± 50 ms each way (simulated) | 1 | 326.44 / 377.01 / 385.96 ms | 0 / 0 |

The gateway's overhead is 0.43 − 0.24 = 0.19 ms median for both passes of a round trip, about 0.1 ms per pass. Decoding a mic frame takes 205.7 ns and encoding an agent frame 250.1 ns, with 1 allocation each. Real packet loss was not measured.

## Concurrent sessions and load

How latency holds up with many sessions at once. Mock providers through the real gateway and orchestrator, with one headless client process per session on the same laptop (fake-provider). Source: `reports/perf.md`.

| Concurrent sessions | Completed | Total p50 / p95 | Residual p95 | Gateway drops / gaps |
|---:|---:|---:|---:|---:|
| 1 | 1 / 1 | 1,301 / 1,301 ms | 3 ms | 0 / 0 |
| 5 | 5 / 5 | 1,318 / 1,320 ms | 20 ms | 0 / 0 |
| 20 | 20 / 20 | 1,296 / 1,299 ms | 19 ms | 0 / 0 |
| 40 | 40 / 40 | 1,296 / 1,305 ms | 21 ms | 0 / 0 |

At 40 sessions the orchestrator runs 40 Silero VADs on one event loop, 2,000 frames per second, and latency did not move. CPU was not profiled, so the ceiling is unknown. Live, 2 concurrent sessions both completed, with totals of 2,183 and 3,020 ms and no gateway drops (live-provider, before tuning). Higher live concurrency was not run, because of the budget and the Cartesia plan: 2 concurrent TTS streams is the Free plan's tier.

## Retrieval quality for grounded answers

How well the answer engine finds the right docs passage, on the pinned uv docs snapshot (version 0.13.6, 524 passages). Retrieval fuses SQLite FTS5 BM25 and `BAAI/bge-small-en-v1.5` embeddings with reciprocal rank fusion, k = 60. The relevant passage for each question is the answer key's `must_cite` section (measured offline). Source: `reports/docs_eval.md`.

| Split | Ranking | Recall at 1 | Recall at 5 | Recall at 10 | MRR |
|---|---|---:|---:|---:|---:|
| dev, 19 questions | BM25 | 0.32 | 0.68 | 0.79 | 0.472 |
| dev, 19 questions | dense | 0.58 | 0.74 | 0.84 | 0.644 |
| dev, 19 questions | fused | 0.53 | 0.79 | 0.89 | 0.649 |
| holdout, 11 questions | BM25 | 0.55 | 0.82 | 1.00 | 0.692 |
| holdout, 11 questions | dense | 0.45 | 0.82 | 0.91 | 0.606 |
| holdout, 11 questions | fused | 0.82 | 1.00 | 1.00 | 0.886 |

These numbers are for the uv docs eval corpus, not for this docs site.

## Grounded answer quality

How well the grounded answers hold up, on 15 held-out questions (11 answerable, 4 not) and 21 adversarial questions: stale, contradicting, injected, unauthorised and unsupported pages (live-provider, text only). Source: `reports/docs_eval.md`.

| Measure | gpt-4.1-nano | gpt-oss-120b, current |
|---|---:|---:|
| Refusal decisions right, holdout | 15 / 15 | 14 / 15 |
| Answers containing every required term | 10 / 11 | 10 / 10 |
| Citations supporting the answer | 15 / 15 | 12 / 12 |
| Adversarial, original 15 | 13 / 15 | 14 / 15 |
| Adversarial, fresh 6 | 6 / 6 | 5 / 6 |
| Answers containing an adversarial claim | 0 | 0 |

The two models are comparable within the ±1 noise seen between runs. gpt-oss-120b falsely refused one question with the right passage retrieved at rank 1. The adversarial failures of both are under-answers, not leaks. The manual audit of 20 answers is not done yet.

## Speech recognition word error rate

Word error rate of Deepgram nova-3 with keyterms on held-out audio, paced in real time (live-provider). Normalisation lowercases and removes punctuation, nothing more. Source: `reports/quality_eval.md`.

| Clips | n | WER |
|---|---:|---:|
| All | 25 | 6.5 % |
| Docs questions, synthetic voice | 15 | 3.2 % |
| LibriSpeech clean | 3 | 1.7 % |
| Slow 0.8× | 1 | 0.0 % |
| Mid-sentence pause 600 ms | 2 | 4.2 % |
| Noisy 5 dB | 2 | 10.8 % |
| Noisy 10 dB | 2 | 26.7 % |

With 2 clips per noisy category, those rows are anecdotes. Part of the 10 dB error is the reference: LibriSpeech keeps dialect spelling, and Deepgram writes standard English. Streaming faster than real time lost the last words of long clips and gave 9.9 % overall, so the eval paces audio as live sessions do.

## Cost of live providers

What live voice turns and this project's measurements cost, from the spend ledger `benchmarks/spend_ledger.json` (live-provider). Every paid call reserves from a budget pool before it runs: $5.00 for Deepgram and OpenRouter together, and 16,000 Cartesia credits.

| Item | Cost | Source |
|---|---:|---|
| LLM per live turn, gpt-oss-120b on Cerebras | $0.00057 median, $0.00025 to $0.0012 (29 turns) | `reports/latency_tuning.md` |
| LLM per live turn, gpt-4.1-nano | $0.00013 (30 sessions) | `reports/perf.md` |
| STT per live turn, Deepgram nova-3 | $0.00083 (30 sessions) | `reports/perf.md` |
| TTS per live turn, Cartesia sonic-3.6 | 138 credits (30 sessions) | `reports/perf.md` |
| Latency tuning work, all studies and runs | $0.123 and 2,580 credits | `reports/latency_tuning.md` |
| Project total after the tuning work | $0.95 of the $5.00 cap; 13,692 of 16,000 credits | `reports/latency_tuning.md` |

The STT, TTS and nano per-turn costs come from the 30 live sessions before the latency tuning; they were not re-measured after it. One Cartesia credit is one character of speech, and the tuning work total is the sum of its four items.
