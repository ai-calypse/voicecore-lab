---
title: Architecture overview
description: The three VoiceCore processes, what each one owns, the one protocol between them, and how a voice turn moves through the system.
sidebar_label: Overview
---

## Three processes, each with one owner

VoiceCore runs as three processes, and each one owns one thing:

- **The browser** owns the audio devices. The TypeScript SDK in `packages/web-sdk` captures the microphone, cuts it into 20 ms frames and plays agent audio.
- **The Go gateway** owns the connection. `services/realtime-gateway` checks the session token, negotiates the audio format, watches the heartbeat, holds the resume window and keeps bounded queues with drop counters.
- **The Python orchestrator** owns the conversation. `services/agent-core` decides who holds the floor, runs speech-to-text, the grounded LLM answer and text-to-speech, and tracks generations.

ADR 0001 (`docs/adr/0001-engine-ownership.md`) records this split. The speech and language models are bought, not built: Deepgram nova-3 for streaming speech-to-text, an OpenAI-compatible model through OpenRouter for the answer, and Cartesia sonic-3.6 for speech. Each sits behind an adapter with a mock twin, so the whole stack also runs offline and for free.

## Why the connection and the conversation run in separate processes

The split keeps network trouble away from the conversation. The gateway absorbs what the network and the client do: dropped sockets, floods, malformed frames and stale tokens. A malformed frame closes the client connection in Go, and a flood is dropped and counted there, before Python sees it.

When a client drops, the gateway keeps the session and its orchestrator socket open for 10 s. A reconnecting browser resumes the same conversation, with its history, instead of starting a new one. The orchestrator never sees a raw browser connection. It gets one WebSocket per session from the gateway, at `ws://<orchestrator>/v1/session/{session_id}`, and spends its time on voice activity detection, endpointing and provider calls.

Abuse limits, such as per-IP session caps, the token rate and the host allow-list, are enforced in Go before any paid provider is touched. Ownership also decides who may drop audio: each process owns one queue of agent audio and fences it on cancel. The [realtime gateway](realtime-gateway.md) and [orchestrator](orchestrator.md) pages cover each side.

## One protocol on both hops

`packages/protocol/SPEC.md` defines one wire protocol for both hops: browser to gateway, and gateway to orchestrator. Each session uses one WebSocket per hop. Audio goes in binary messages, one frame per message. Control events go in text messages, one JSON object per message.

An audio frame is a 28-byte big-endian header followed by mono PCM16 little-endian samples. Mic frames are kind 1 at 16 kHz with 320 samples (20 ms). Agent frames are kind 2 at 24 kHz and carry the `generation_id` that produced them. Control events have a `type` and a table of required fields. A receiver rejects an unknown type or a missing field and ignores extra fields.

Because both hops share one format, the gateway forwards frames and events without translating them. It answers `hello` and `ping` itself and adds `client.resumed` upstream. Golden vectors in `packages/protocol/vectors/` are checked by the TypeScript, Go and Python codecs, so the three implementations cannot drift apart. The [wire protocol reference](../reference/wire-protocol.md) lists every field.

## The path of one voice turn

1. The browser captures the microphone in an AudioWorklet, resamples it to 16 kHz and sends one 20 ms PCM16 frame every 20 ms.
2. The gateway checks each frame's sequence number, counts duplicates, stale frames and gaps, and queues the frame for the orchestrator.
3. The orchestrator runs Silero VAD on every frame. Only speech goes to Deepgram, with 300 ms of pre-roll before it and 600 ms of hangover after it. The client gets `user.speech_started`.
4. The endpoint policy decides the user has finished. With live providers the default is eager: it asks Deepgram to finalize after 200 ms of silence and ends the turn on a punctuated final, or after 800 ms of silence otherwise. Mock mode uses a fixed 800 ms.
5. The orchestrator retrieves passages locally, then streams a grounded LLM answer. A sentence is released only with a valid citation, and each sentence goes to Cartesia in one context per generation.
6. Agent audio comes back at 24 kHz, is cut into 20 ms frames tagged with the generation, and flows through the gateway to the browser along with `answer.sources` and `agent.text`.
7. The browser plays the frames in order and reports `playout.started` and `playout.stopped` on its own clock.

## How a cancel reaches all three processes

Barge-in works because of one rule. Every agent frame carries the `generation_id` that produced it, and every process that queues agent audio keeps a fence. When generation g is cancelled, because the user interrupts, types a new question or reconnects, each queue owner sets its fence to at least g and drops every frame at or below it, including audio already queued.

- The orchestrator checks the generation before every frame it sends. It stops the LLM task, tells the TTS adapter, and sends `agent.cancel`.
- The gateway sees `agent.cancel` pass through, raises its own fence and purges matching audio from its client-bound queue.
- The browser playout flushes its queue and answers `cancel.ack` with `played_until_seq`, the last frame it rendered.

The TTS adapter drops late audio of a cancelled generation too, because Cartesia's cancel only stops requests that have not started. Generation IDs rise by one per generation and never repeat, so a fence never has to move down. [Generations and cancellation](../concepts/generations-and-cancellation.md) explains the idea in depth.

## Where session state lives

Each process keeps only the state it owns, and no process reads another's state. Everything they share travels through the protocol. Because the orchestrator's session lives as long as its gateway socket, and the gateway keeps that socket open during the resume window, a reconnect within 10 s keeps the conversation history.

| Process | State it keeps | Lifetime |
|---|---|---|
| Browser SDK | session ID for resume, mic stream ID, clock offset from the last pong, playout queue and fence, underrun total | the page |
| Gateway | session map, per-IP session counts, token buckets, last sequence per mic stream, revoked streams, outbound fence, newest generation seen, both queues, drop counters | the session plus the 10 s resume window |
| Orchestrator | floor and turn state, newest generation and fence, transcript, the last 8 history messages, audio sent per generation as the echo reference, provider sockets | one gateway connection |
| Disk | spend ledger `benchmarks/spend_ledger.json`, trace files when tracing is on | across runs |

The budget ledger is the only state that outlives a session. Every live session reserves its worst-case spend there before it builds a paid provider.

## How the system handles failures

Each failure below has a test, and each is handled by the process that owns the failing part. The gateway handles the network and the client. The orchestrator handles providers and turns. The browser handles its own devices. A failure in one place leaves the others running: losing the microphone, for example, still leaves typed questions working. The rule throughout is that every turn ends with an answer and an end, even if that answer is a reprompt or text without speech.

| Failure | Behaviour | Where |
|---|---|---|
| Network drop | the gateway keeps the session and the upstream socket for 10 s; on resume it fences the old generation and the orchestrator cancels it | gateway `session/`, `Session.on_event` |
| Client floods or misbehaves | bounded queues drop the oldest audio and count it; close codes 1007, 1008, 4001 to 4003 | gateway |
| STT returns nothing | reprompt after waiting up to 5 s | `Session._after_endpoint` |
| LLM stall or HTTP 429 | reprompt after 8 s; backoff 1, 2, 4 s, then "I'm busy" | `Session._generate` |
| TTS failure | the text answer is delivered; one retry on a fresh stream if nothing was heard yet | `Session._retry_tts` |
| Mic revoked | that stream is ignored; text keeps working | `Session.on_event` |
| Budget exhausted | live adapters cannot be built without a reservation; per-session caps end the voice path | `budget.py`, `providers/factory.py` |

## How traces from three processes line up

Every process writes the same JSON-lines trace event shape, defined in SPEC section 5. The gateway writes it when started with `-trace`, the orchestrator writes one file per session with `--trace-dir`, and the headless client writes its event log. Each process stamps events with its own monotonic clock, so the raw times cannot be compared directly.

`harness/session_timeline.py` puts all of them on the client's clock. The gateway offset comes from ping and pong, NTP style, using the exchange with the smallest round trip. The orchestrator offset comes from mic frames: the minimum of arrival time minus capture end, so it includes the smallest one-way uplink delay. The demo's `?lab=1` panel draws the merged timeline.

Transcript and answer text are never traced unless a run asks for it. The [trace events reference](../reference/trace-events.md) lists every event, and [measure latency](../guides/measure-latency.md) shows how the timeline turns into stage latencies.

## Repository map

The repository is a pnpm workspace for the TypeScript parts, a Go module per Go part, and a uv project for Python. The table shows where each part of the architecture lives, so you can go from a page in these docs to the code behind it. Paths are relative to the repository root. Each process lives in its own folder, and the protocol spec with its golden vectors is the one thing all three share.

| Path | What it holds |
|---|---|
| `packages/protocol` | `SPEC.md`, golden vectors, the TypeScript codec |
| `packages/web-sdk` | browser SDK: capture, `VoiceClient`, playout, the headless Node client |
| `services/realtime-gateway` | Go gateway: `cmd/gateway`, the `session` and `protocol` packages, `cmd/wsload` and `cmd/fakeorch` for benchmarks |
| `services/agent-core/voicecore` | Python orchestrator: `server.py`, `runtime/`, `turntaking/`, `providers/`, `answer/`, `budget.py`, `trace.py` |
| `apps/demo` | demo page, widget and Playwright tests |
| `apps/docs` | this documentation site |
| `harness` | scenario runners, trace timeline, benchmarks, the CI gate |
| `experiments` | RTP jitter buffer lab and the Pion WebRTC spike |
| `fixtures` | audio clips and a docs snapshot |
| `reports`, `benchmarks` | measured results and raw data |
| `docs` | ADRs and design notes |
