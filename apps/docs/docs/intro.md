---
title: VoiceCore documentation
sidebar_label: Introduction
description: What VoiceCore is, which parts it builds and which it buys, what it has measured, and how these docs are organised.
slug: /
---

## What VoiceCore is

VoiceCore Lab is a real-time voice agent built as a voice AI systems engineering portfolio. It shows the work underneath voice AI: browser audio capture and playout, a Go real-time gateway, turn-taking with an echo gate, barge-in that silences the agent, a grounded answer engine, and the tracing and benchmarks that measure all of it.

It runs as three processes that share one wire protocol:

- the **browser SDK** owns the audio devices;
- the **Go gateway** owns the connection;
- the **Python orchestrator** owns the conversation.

The voice assistant in the corner of this site is VoiceCore itself. It answers from these pages only and opens the section it cites. With mock providers it needs no keys and spends nothing. With live providers it uses Deepgram for speech-to-text and text-to-speech, and a language model through OpenRouter. Cartesia is an alternative for text-to-speech.

## What a voice agent is

A voice agent is a program you talk to and that talks back. It captures your microphone audio, decides when you have finished speaking, turns your speech into text, asks a language model for an answer, turns that answer into speech and plays it to you. While it speaks, it keeps listening, so you can interrupt it. Every stage adds delay, and the delays add up. The engineering is in deciding quickly and correctly that a turn has ended, starting each stage as early as possible, and stopping the agent's audio the moment you start talking. See [how a voice agent works](concepts/how-a-voice-agent-works.md) for the full loop.

## Which parts VoiceCore writes itself

ADR 0001 (`docs/adr/0001-engine-ownership.md`) draws the line between owned code and bought inference. Everything between the microphone and the speaker is this repository's code:

- **Browser SDK** in TypeScript: AudioWorklet capture, resampling to 16 kHz, PCM16 framing, the WebSocket session client, and ordered playout that flushes on cancel.
- **Wire protocol:** one binary frame format and one set of JSON events for both hops, with golden test vectors shared by TypeScript, Go and Python.
- **Real-time gateway** in Go: token auth, heartbeat, resume window, bounded queues with drop counters, and the outbound generation fence.
- **Orchestrator** in Python asyncio: turn-taking (endpointing, echo gating, barge-in) and the generation runtime (generation IDs, cancellation, TTS ordering, recovery).
- **Provider adapters** with mock and live versions, and the budget guard every live adapter must pass.
- **Answer engine:** docs ingestion, keyword and embedding retrieval fused by rank, and citation validation.
- **Evidence tooling:** fixtures, scenario runner, trace timeline, benchmarks and evaluation reports.

## Which parts VoiceCore buys

Speech recognition, the language model and speech synthesis are bought through replaceable adapters and are never claimed as VoiceCore's work:

| Capability | Provider and model |
|---|---|
| Streaming speech-to-text | Deepgram nova-3 |
| Language model | `openai/gpt-oss-120b` through OpenRouter, Cerebras first, reasoning effort low |
| Streaming text-to-speech | Deepgram Aura-2, `aura-2-thalia-en`; Cartesia sonic-3.6 with `--tts cartesia` |
| Voice activity detection | Silero VAD, runs locally |
| Embeddings | fastembed small ONNX model, runs locally |

The hosted Deepgram Voice Agent API is used only as a latency baseline. ADR 0001 rules out delegating orchestration, turn-taking or cancellation to a managed voice-agent product. Non-goals include billing, SaaS plans, tenant isolation, voice cloning and telephone carrier certification.

## Headline measured results

Every number carries its conditions. Live means real providers over a residential network, with every process on one Apple M4 laptop. Mock means scripted providers on the same machine. Each number comes from a report in the repository's `reports/` folder, where the commands to reproduce it are listed.

| What | Result |
|---|---|
| You stop speaking until the first agent audio plays | p50 841 ms, p95 1,520 ms (live, n = 15); p50 2,317 ms before tuning (live, n = 15) |
| Detecting the end of your turn | p50 340 ms (live, n = 15) |
| Same path with mock providers | p50 1,320 ms, p95 1,440 ms (mock, n = 216) |
| You start talking until the agent goes silent | p50 303 ms, 8 of 8 silenced (live, n = 8) |
| False barge-ins on echo only | 0 of 4 (live, simulated room echo, n = 4) |
| Gateway overhead per round trip | 0.19 ms median (mock, loopback, 500 frames) |
| Grounded answers, held-out questions | 14 of 15 refusal decisions right, 12 of 12 citations supporting (live, gpt-oss-120b, uv docs eval set) |
| Concurrent sessions | 40 of 40 complete, p95 1,305 ms (mock, n = 40) |

The hosted Deepgram Voice Agent measured 972 ms (live, n = 3). Samples are small, so these numbers rank design choices; they are not production rates.

## How these docs are organised

The sidebar has five groups:

- **Getting started:** run VoiceCore with mock providers in the [quickstart](getting-started/quickstart.md), switch to [live providers](getting-started/live-providers.md), and [embed the widget](getting-started/embed-the-widget.md) on your own page.
- **Concepts:** how a voice agent works, latency, turn-taking, endpointing, barge-in and echo, generations and cancellation, and grounded answers.
- **Architecture:** the [overview](architecture/overview.md), then one page each for the browser SDK, the realtime gateway and the orchestrator, plus why VoiceCore uses WebSocket rather than WebRTC.
- **Guides:** measure latency, tune latency, add your own docs, telephony, and [troubleshooting](guides/troubleshooting.md).
- **Reference:** the wire protocol, configuration, trace events, providers, benchmarks, and the [FAQ](faq.md).

Start with the quickstart if you want to run it. Start with the concepts if you want to understand it.
