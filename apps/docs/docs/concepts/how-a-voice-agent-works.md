---
title: How a voice agent works
description: The cascade from microphone to speaker, what a turn and a generation are, and which parts of the pipeline this repository writes itself.
---

## The cascade from microphone to speaker

A cascaded voice agent chains separate streaming stages, each one feeding the next. In this repository the chain has six stages: capture, voice activity detection (VAD) and turn-taking, speech to text (STT), the language model (LLM), text to speech (TTS) and playout. Three processes run them. The browser owns the audio devices, the Go gateway owns the connection, and the Python orchestrator owns the conversation. The gateway does not change the audio; it authenticates the session, checks frame order and forwards frames between the browser and the orchestrator. Every stage works on small pieces, so the agent can start speaking before the whole answer exists.

| Stage | Runs in | What it does here |
|---|---|---|
| Capture | Browser SDK | AudioWorklet, resampling to 16 kHz, 20 ms PCM16 frames |
| VAD and turn-taking | Orchestrator | Silero VAD on every frame, the floor state machine, the echo gate |
| STT | Deepgram nova-3 | Streaming partial and final transcripts, Finalize at the endpoint |
| LLM | gpt-oss-120b through OpenRouter | Grounded answer from retrieved docs, streamed as tokens |
| TTS | Cartesia sonic-3.6 | Audio per sentence, one context per generation |
| Playout | Browser SDK | One queue per generation, fence on cancel, playout events |

### Capture in the browser

The SDK captures the microphone with an AudioWorklet, which delivers 128-sample blocks. A 64-tap windowed-sinc resampler converts them to 16 kHz, and a framer cuts 320-sample frames: 20 ms of 16-bit little-endian PCM. Each frame gets a 28-byte big-endian header (version, kind, flags, stream, sequence, capture time, generation and sample count) and leaves as one WebSocket binary message. No audio is sent before the user consents. The Go gateway checks sequence numbers, counts duplicates, stale frames and gaps, and forwards frames to the orchestrator through a bounded 50-frame queue. A WebSocket runs over one TCP connection, so frames cannot arrive out of order, and the gateway needs no reorder buffer.

### Voice activity detection and turn-taking

The orchestrator runs Silero VAD on every 20 ms frame and passes the speech probability to the floor, a small state machine that decides who holds the floor. The floor reports three things: the user started speaking, the user interrupted the agent (a barge-in), and the user finished (the endpoint). Turn-taking also decides which audio reaches STT. Only speech, plus 300 ms of pre-roll before it, is sent, because STT is billed per second. Before tuning, the endpoint decision was the largest single delay in a turn: 861 of 2,317 ms (live p50, n = 15). That is why this repository writes and measures turn-taking itself. See [Turn-taking](./turn-taking.md) and [Endpointing](./endpointing.md).

### Speech to text

The STT stage is Deepgram nova-3 over a streaming WebSocket. It returns interim transcripts while the user speaks and final transcripts for settled stretches of audio. The adapter boosts the project's vocabulary with keyterms such as uv, uvx and uv sync. When the floor reports an endpoint, the session sends Deepgram a Finalize message so the last words come back as a final right away. In the live breakdown run, the transcript was ready p50 0.6 ms after the endpoint (live, n = 10), because Finalize had already returned it. The session waits until there is a final and no interim text is left, for at most 5 s. An empty transcript gets a reprompt: "Sorry, could you say that again?". With the eager policy, Finalize goes out earlier, after 200 ms of silence.

### Language model

Before the LLM sees the question, the answer engine retrieves passages locally. It combines FTS5 keyword search and embedding search with reciprocal rank fusion, and builds a grounded prompt from the results. The prompt goes to `openai/gpt-oss-120b` through OpenRouter's OpenAI-compatible API, with Cerebras as the first provider and reasoning effort low. Tokens stream back as they are generated. A sentence is released to TTS only once it, or a later sentence of the same answer, carries a valid `[n]` citation, and uncited text left at the end is dropped. If no token arrives for 8 s, the agent says "Sorry, could you say that again?". After an HTTP 429 before any answer text, it backs off for 1, 2 and 4 s, then says "I'm busy right now". See [Grounded answers](./grounded-answers.md).

### Text to speech

A chunker cuts the token stream at sentence ends: a `.`, `!` or `?` followed by whitespace, or a newline. TTS can therefore start on the first sentence while the LLM is still writing the rest. Before synthesis, citation markers such as `[1]` are removed, and a raw URL is spoken as "the link in the chat". Cartesia sonic-3.6 synthesizes over one WebSocket with one context per generation. The socket is opened when the session starts, so the first answer does not wait for the handshake. The orchestrator cuts the returned 24 kHz audio into 20 ms frames, stamps each frame with its generation ID and sends it back through the gateway.

### Playout in the browser

The SDK plays agent audio through an AudioContext at 24 kHz, from one queue per generation. When the first sample of a generation is rendered, the client sends `playout.started` with its own clock time. When the audio ends or is cancelled, it sends `playout.stopped` with the reason `done` or `cancel`. These events tell the orchestrator what the user has actually heard. The echo gate uses them to compare the microphone with the audio being played, and the latency metric ends at `playout.started`. On a cancel, playout flushes everything at or below the cancelled generation and replies with `cancel.ack`, whose `played_until_seq` says how far playback got.

## Why every stage streams

A voice turn feels fast only if each stage starts on partial input. In this repository the microphone sends 20 ms frames, STT returns partial transcripts during speech, the LLM streams tokens, TTS starts on the first full sentence, and playout starts on the first audio frame. What the user waits for is the sum of each stage's delay to its first output, not the time to produce the whole answer. After tuning, the stage medians were 340 ms to detect the turn end, 340 ms from the LLM request to the first token, 145 ms from that token to the first TTS audio, and 26 ms of transport and playout start (live p50, n = 15). The whole turn was p50 841 ms (live, n = 15). See [Latency](./latency.md).

## What a turn is

A turn is one thing the user says or types, plus the agent's reply to it. A spoken turn starts when the floor reports speech start, and it gets the next turn ID: `t1`, `t2` and so on. The session moves through the states listening, user speaking, thinking and speaking, and returns to listening when the answer finishes playing. Clients follow the turn through events that carry its `turn_id`: `user.speech_started`, `transcript.partial` while the user speaks, `transcript.final` after the endpoint, and `agent.generation_started` when the answer begins. A typed question (`text.input`) also starts a turn, and it skips turn-taking and STT. Speech that starts while the agent is talking starts a new turn too, as a barge-in.

## What a generation is

A generation is one attempt to answer, and one turn can have more than one. Generation IDs start at 1, increase by one per generation in a session and never repeat. Every agent audio frame carries its `generation_id` in the frame header, and every answer event names its generation. A generation is alive only while it is the newest one and above the fence. Starting a new generation cancels the active one. Cancelling generation g sets the fence to g in the orchestrator, the gateway and the browser playout, and each of them drops every agent frame at or below g, including audio already queued. This is how a barge-in, the continuation merge or a reconnect stops stale audio at every hop. See [Generations and cancellation](./generations-and-cancellation.md).

## Cascade compared with a hosted voice agent

A hosted voice agent, such as the Deepgram Voice Agent API, runs STT, LLM and TTS behind one WebSocket and does its own endpointing. You stream audio in and get audio out. That is less code, but it hides the work this repository exists to show: turn-taking, cancellation, transport and latency accounting. ADR 0001 therefore uses the hosted agent only as a baseline, and no orchestration, turn-taking or cancellation logic may be delegated to it. The baseline ran nova-3, `gpt-4o-mini` and Deepgram's own TTS. It measured a median of 972 ms from speech end to the first agent audio frame received (live, n = 3). The tuned cascade measured p50 841 ms to the first sample rendered (live, n = 15). The conditions were not matched; see [the baseline comparison](./latency.md#comparison-with-the-hosted-deepgram-baseline).

## What this repository writes and what it buys

ADR 0001 splits the system into code written and tested here, and inference bought through replaceable adapters. Every live adapter must pass a budget guard (`voicecore/budget.py`) before it can be built, and the whole project has a $5.00 cap on paid use. The bought services are never presented as this repository's work. The Deepgram Voice Agent is used only as a measured control. Non-goals include voice cloning, training speech models, a distributed SFU and unmeasured latency claims.

| Owned code | Bought or reused |
|---|---|
| Browser SDK: capture, resampling, framing, session client, playout | Streaming STT: Deepgram nova-3 |
| Wire protocol with golden vectors in TypeScript, Go and Python | LLM: `openai/gpt-oss-120b` via OpenRouter, Cerebras first |
| Go gateway: auth, heartbeat, resume window, bounded queues, fence | Streaming TTS: Cartesia sonic-3.6 |
| Orchestrator: turn-taking module and generation runtime | VAD model: Silero VAD (ONNX), runs locally |
| Provider adapters, mocks and the budget guard | Embeddings: a small fastembed ONNX model, runs locally |
| Answer engine, harness, benchmarks and reports | Hosted baseline only: Deepgram Voice Agent API |

## How failures are handled along the cascade

Each stage of a cascade can fail on its own, so each failure has its own rule, and each rule has a test. A network drop does not end the conversation, because the gateway holds the session for a resume window. A slow or failing provider produces a spoken fallback instead of silence. A TTS failure still delivers the text answer. If the user revokes the microphone, text input keeps working. The table lists each rule and where it lives.

| Failure | Behaviour | Where |
|---|---|---|
| Network drop | The gateway keeps the session and upstream socket for 10 s; on resume the old generation is fenced and cancelled | gateway `session/`, `Session.on_event` |
| Client floods or misbehaves | Bounded queues drop the oldest frame and count it; close codes 1007, 1008, 4001–4003 | gateway |
| STT returns nothing | Reprompt after 5 s | `Session._after_endpoint` |
| LLM stall or HTTP 429 | Reprompt after 8 s; back off 1, 2 and 4 s, then "I'm busy" | `Session._generate` |
| TTS failure | The text answer is delivered; one retry on a fresh stream if nothing was heard yet | `Session._retry_tts` |
| Microphone revoked | That stream is ignored; text keeps working | `Session.on_event` |
| Budget exhausted | Live adapters cannot be built without a reservation | `budget.py`, `providers/factory.py` |
