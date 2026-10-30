---
title: Tune voice turn latency
sidebar_label: Tune latency
description: A walkthrough of the tuning that took the live voice turn from p50 2,317 ms to 841 ms, with the measurement, each change, the answer-quality check and what was not tried.
---

This guide walks through the tuning that took a live VoiceCore voice turn from p50 2,317 ms to p50 841 ms (live, n = 15, the same 15 dev docs questions before and after). Every step was measured first, changed once, then measured again. The metric is the one from [Measure latency](measure-latency.md): labelled end of the user's speech to the first agent sample rendered by the client. The full record is `reports/latency_tuning.md`.

## Measure before you change anything

Tuning starts with a per-stage breakdown, not a guess. Run the live benchmark, then break it down:

```bash
uv run python harness/runner/wss.py --providers live --sequential --tail 8 --clips <clip ids>
uv run python harness/latency.py benchmarks/raw/<run folder>
```

`latency.py` splits each turn into endpoint delay, STT settle, LLM first token, TTS first audio and a residual for transport and playout start. Each stage is measured on one clock, so the stages stay exact even though three processes are involved.

Two rules kept this work honest:

- **Change one stage at a time.** Then each gain belongs to one change.
- **Compare on the same clips.** The before and after runs used the same 15 dev docs questions, spoken by the same synthetic voice, on the same laptop (Apple M4, macOS 26.5.2, providers over a residential network).

Samples are small (6 to 37 per number), so they rank configurations. They are not production rates.

## Where the time went before tuning

The starting point was fixed 800 ms endpointing and `openai/gpt-4.1-nano` through OpenRouter, run `wss_live_fixed_20261030T020448Z` (live, n = 15):

| Stage | p50 | p95 |
|---|---:|---:|
| Total | 2,317 ms | 3,102 ms |
| Endpoint delay | 860 ms | 900 ms |
| STT settle | 0.7 ms | 0.8 ms |
| LLM first token | 939 ms | 1,758 ms |
| TTS first audio | 456 ms | 531 ms |
| Residual (transport and playout start) | 13 ms | 24 ms |

Two stages dominated: waiting for the end of the turn, and waiting for the model's first token. Transport was negligible. STT settle was under 1 ms: the final transcript was already there when the endpoint fired. The target was about 1,000 to 1,100 ms, close to the hosted Deepgram Voice Agent's 972 ms (n = 3, not matched conditions).

## Pick the LLM by first-token benchmark

Model choice was made with a text-only benchmark, `harness/llm_ttft.py`, before any full-stack run. It sends the real grounded prompt the answer engine builds (5 retrieved uv docs passages and a question, about 1,200 input tokens) through OpenRouter, with the provider pinned and fallbacks off. Run it with `uv run python harness/llm_ttft.py`; `--n` sets how many questions per configuration (default 6).

For each configuration it records three times: the first answer token (content, not reasoning), the end of the first sentence (when TTS could start) and completion. It reserves $0.05 from the budget first and writes `reports/llm_ttft.json`.

| Config (live, n = 6 each) | First token p50 / max | First sentence p50 / max |
|---|---:|---:|
| gpt-4.1-nano | 574 / 2,061 ms | 791 / 2,691 ms |
| gpt-oss-120b, Cerebras, effort low | 300 / 514 ms | 314 / 538 ms |
| gpt-oss-120b, Groq, effort low | 451 / 744 ms | 505 / 792 ms |
| gpt-oss-120b, BaseTen, effort low | 508 / 579 ms | 579 / 718 ms |
| gpt-oss-20b, Groq, effort low | 514 / 754 ms | 538 / 768 ms |

`openai/gpt-oss-120b` on Cerebras won: it streams the whole two-sentence answer in about the time nano needs for its first token.

## Why the reasoning model needed a larger token limit

gpt-oss-120b is a reasoning model. Even at reasoning effort low it wrote 31 to 77 reasoning tokens per answer in the benchmark, and reasoning tokens count against `max_tokens`. An 80-token limit sized for a short spoken answer would have to cover the reasoning too. So the answer engine's limit went from 80 to 200 (`AnswerEngine`, `max_tokens=200`).

The adapter now sends these defaults on every call:

- model `openai/gpt-oss-120b`;
- OpenRouter provider order Cerebras first, with fallbacks allowed, so a Cerebras outage makes turns slower instead of failing (the benchmark pinned Cerebras with no fallback);
- reasoning effort `low`;
- temperature 0.

The faster model costs more per turn: $0.00057 median ($0.00025 to $0.0012 over 29 live turns) against $0.00013 for nano. Live first token went from p50 939 ms to 340 ms.

## Keep provider connections warm

A cold connection adds a TLS handshake to the user's turn. The session opens provider connections when it starts, not on the first turn: `Session.start` calls `warm()` on every provider that has one.

- **Deepgram:** the STT socket opens at session start (the handshake took about 250 ms). A KeepAlive message every 4 s without audio holds it open, because Deepgram closes a socket that gets no audio for 10 s.
- **OpenRouter:** the LLM adapter uses one shared `httpx` connection pool per event loop with a 60 s keep-alive. The `httpx` default of 5 s closed the connection while the user was still talking, so each turn paid a fresh TLS handshake. At session start the adapter also sends a free `GET /key` request to open the connection.

The keep-alive change has no separate number: its gain is part of the LLM first-token drop from 939 to 340 ms p50. The Deepgram socket was already opened at session start before this work.

## Pre-open the TTS socket

The Cartesia WebSocket handshake took 250 to 330 ms, and before tuning it happened at the first answer, inside the user's wait. Now `OnDemandTTS.warm()` in `server.py` calls the TTS module's `open_socket()` at session start, and the TTS stream adopts that socket when the session first speaks. Deepgram Aura-2, the speech default since 2026-10-30, uses the same pre-opened socket.

Opening the socket spends nothing, so the TTS budget is still reserved only on first speech. That keeps idle sessions from holding the pool, as a security review on 2026-10-30 required. If the early open fails, `open_socket` returns nothing and the stream connects on first use as before.

Result: TTS first audio went from p50 456 ms to 145 ms with Cartesia (live, n = 15). With Deepgram Aura-2 it was p50 115 ms (live, n = 6). That stage starts at the LLM's first token and includes the wait for the first full sentence of the answer.

## Choose an endpoint policy from recorded live finals

The endpoint policy was chosen offline, from real Deepgram finals, so each candidate costs nothing to evaluate. `harness/endpoint_study.py --record` streamed 37 dev clips (25 docs questions and 12 LibriSpeech clips) to Deepgram in real time, ran Silero VAD alongside, sent Finalize after 200 ms of VAD silence, and logged every final with its arrival time. Without `--record`, it replays that log through each policy.

| Policy (live finals, replayed, n = 37) | Delay p50 / p95 | Early cutoffs |
|---|---:|---:|
| fixed 300 ms | 360 / 440 ms | 14 |
| fixed 600 ms | 660 / 740 ms | 3 |
| fixed 800 ms, the previous default | 860 / 940 ms | 0 |
| eager: punctuated final and 200 ms silence, else 800 ms | 400 / 540 ms | 5 |
| eager with 400 ms silence, else 800 ms | 460 / 540 ms | 4 |

Requiring 200, 250 or 300 ms of silence gave identical results, because Deepgram's final arrives about 100 ms after Finalize. Eager at 200 ms was chosen, with a merge to absorb its 5 early cutoffs.

## How eager endpointing decides the end of a turn

Eager endpointing is now the default with live providers. It combines the VAD's silence with the STT's punctuation:

1. After 200 ms of VAD silence, the session sends Deepgram a Finalize, once per pause.
2. If a final transcript that ends in `.`, `?` or `!` has arrived and the silence is at least 200 ms, the turn ends.
3. If no punctuated final comes, the turn ends after 800 ms of silence, as the fixed policy would.

The code is `Policy("eager", asr_silence_ms=200)` in `server.py`, with the logic in `turntaking/floor.py` and `runtime/session.py`. Live, the time to detect the end of the turn went from p50 860 ms to 340 ms (n = 15).

Mock mode keeps fixed 800 ms. The mock STT returns its canned final at every pause, so eager would end every mock turn early. To choose a policy yourself, pass `--policy fixed`, `adaptive`, `asr_assisted` or `eager` to the orchestrator.

## Merge early cutoffs into one question

Eager endpointing sometimes ends a turn inside a question. Deepgram punctuates a pause ("How do I install uv?" … "On a Mac or Linux machine?"), the turn ends, and generation 1 starts. The continuation merge repairs that.

When the user speaks again within 2.5 s of an endpoint (`MERGE_WINDOW_US`), and before any of the answer is audible, the session:

1. cancels generation 1, which has not played yet;
2. puts the earlier text in front of the new transcript;
3. answers the whole question once, as generation 2.

Live, this happened in 6 of 27 turns, and each was answered from the complete question. In all 6 the client acknowledged the cancel with `played_until_seq: -1`, so nothing of generation 1 was heard. The total is still measured from the end of the whole utterance, so a merge costs no reported latency. It costs one extra LLM call.

Once the early answer is audible, new speech is a barge-in and a new question. That is deliberate: a user who says "stop" should not get the old question glued on.

## Check answer quality after a model change

A faster model is no gain if it answers worse. After the switch, the text-only grounded eval (`uv run python harness/answer_eval.py --split holdout`) ran again on the same held-out and adversarial questions. Text-only means no TTS credits are spent.

| Measure (live) | gpt-4.1-nano | gpt-oss-120b |
|---|---:|---:|
| Refusal decisions right, holdout | 15 / 15 | 14 / 15 |
| Answers with every required term | 10 / 11 | 10 / 10 |
| Citations supporting the answer | 15 / 15 | 12 / 12 |
| Adversarial, original set | 13 / 15 | 14 / 15 |
| Adversarial, fresh set | 6 / 6 | 5 / 6 |

The two models are comparable within the ±1 noise seen between runs. gpt-oss is a little more cautious. It falsely refused q13 ("How do I pin the Python version for my project?") with the right passage at rank 1. The eval also needed a scoring fix: gpt-oss writes non-breaking hyphens ("free‑threaded"), and two correct answers were scored as misses until the term check treated every Unicode hyphen like an ASCII one.

## Results of the tuning

Same 15 dev docs questions, full stack: headless SDK client, Go gateway, orchestrator, Deepgram, OpenRouter and Cartesia sonic-3.6 for speech.

| Run (live) | Total p50 / p95 | Turn end detected p50 | LLM first token p50 | TTS first audio p50 |
|---|---:|---:|---:|---:|
| Before: fixed 800 ms, gpt-4.1-nano (n = 15) | 2,317 / 3,102 ms | 860 ms | 939 ms | 456 ms |
| After: eager, gpt-oss-120b on Cerebras (n = 15) | 841 / 1,520 ms | 340 ms | 340 ms | 145 ms |
| After, hard audio: noisy, slow, mid-sentence pauses (n = 12) | 841 / 1,218 ms | 340 ms | 366 ms | 134 ms |

13 of the 15 docs turns finished under 1,000 ms. The slow ones were q21, where the LLM's first token took 1,013 ms, and q17, where no punctuated final arrived and the turn fell back to 800 ms of silence.

The hosted Deepgram Voice Agent measured 972 ms (n = 3), but to the first audio frame received, not the first sample rendered, and not under matched conditions. Treat the comparison as a rough marker.

## Reproduce or revert the tuned settings

The tuned settings are the live defaults, so `python -m voicecore.server --providers live` runs them. Every change can be undone with an orchestrator flag:

- `--policy fixed` restores fixed 800 ms endpointing.
- `--llm-model openai/gpt-4.1-nano --llm-provider any --llm-reasoning none` restores the previous LLM. `any` lets OpenRouter route; `none` omits the reasoning setting for a model without it.

Through the benchmark runner, pass orchestrator flags with `--server-arg`, and name the run with `--label` so the folders stay apart:

```bash
uv run python harness/runner/wss.py --providers live --sequential --tail 8 --label nano \
  --server-arg=--llm-model=openai/gpt-4.1-nano --server-arg=--llm-provider=any \
  --server-arg=--llm-reasoning=none --clips <clip ids>
```

`harness/latency.py` now counts turns with more than one generation, measured to the generation that played, so merged turns appear in the percentiles.

## What the tuning work cost

All spend goes through the budget ledger, `benchmarks/spend_ledger.json`. The costs of this tuning work:

- LLM first-token study: $0.008.
- Endpoint study (live STT): $0.037.
- Live end-to-end runs, 29 turns: $0.043 and 2,580 Cartesia credits.
- Two answer evals: $0.035.

After this work the project total stood at $0.95 of the $5 cap, and 13,692 of the 16,000 planned Cartesia credits. The offline replay in the endpoint study is what kept this cheap: it recorded the live finals once, then evaluated twelve policies at no cost.

## What was not tried

Three things were left out of this round, and they are the obvious next steps:

- **Speculative LLM calls on partial transcripts.** Starting the answer before the endpoint would remove most of the remaining 340 ms of endpoint wait, at the cost of more LLM calls. Not tried.
- **Repeat runs at different times of day.** LLM provider latency moved by 2× between batches in earlier runs, so the p95 of 1,520 ms should be checked again before it is quoted widely.
- **The browser widget, live.** The widget was not measured live in this work. It uses the same SDK and server path as the headless client.

Remember that each number here comes from 6 to 37 samples. Re-measure on your own clips before you rely on them.
