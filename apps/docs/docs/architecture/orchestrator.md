---
title: Orchestrator
description: How the Python orchestrator runs one conversation per gateway connection, builds paid providers only against a budget, opens provider sockets early, and fences generations.
---

## What the Python orchestrator owns

The orchestrator in `services/agent-core/voicecore` owns the conversation. It is one asyncio process that keeps one `Session` per gateway connection. A session decides who holds the floor, sends speech to speech-to-text, streams a grounded answer from the LLM, cuts it into sentences for text-to-speech, and sends agent audio and events back through the gateway.

| Module | Job |
|---|---|
| `server.py` | WebSocket server, provider setup, the per-session handler |
| `runtime/session.py` | the generation runtime: turns, generations, fence, recovery |
| `turntaking/floor.py`, `turntaking/vad_silero.py` | endpoint policies, echo gate, barge-in, Silero VAD |
| `providers/` | STT, LLM and TTS contracts, mock adapters, live Deepgram STT and TTS, OpenRouter and Cartesia adapters |
| `answer/` | docs ingestion, hybrid retrieval, grounded answers |
| `budget.py` | spend guard and ledger |
| `trace.py` | trace events |

The orchestrator never talks to the browser directly. Every byte comes through the Go gateway, which has already checked the token, the audio format and the sequence numbers.

## How the server handles one session connection

`server.py` serves `ws://HOST:PORT/v1/session/{id}`. The gateway dials this URL once per session, and the last path segment becomes the session ID. For each connection the handler:

1. builds the providers, mock or live; if a live budget reservation is refused, it sends `session.ended{reason: "budget"}` and closes;
2. opens a trace file `{id}.jsonl` when `--trace-dir` is set;
3. creates an `AnswerEngine` over the shared docs index, and a `Session` with a fresh Silero VAD and the chosen endpoint policy, then calls `session.start()`;
4. reads messages until the socket closes: binary mic frames go to `session.on_frame`, and text events go to `session.on_event`;
5. in a `finally` block, closes the session and the trace file, and settles every budget reservation with what was actually used.

A closed socket and a decode error both end the loop the same way, so a session always closes and settles its spend. Silero VAD runs inline on the event loop. A `ponytail:` note in the handler marks where it would move to a thread if many sessions saturate one core.

## How the orchestrator reports health and drains

The session port also answers plain HTTP. `GET /healthz` returns 200 `{"status": "ok", "providers": "mock", "version": "dev"}` as long as the process runs; the e2e tests use `providers` to refuse an orchestrator with live (paid) providers. `GET /readyz` returns 200 only once the VAD model and docs index are loaded and no drain has begun, otherwise 503 with `{"ready": ..., "draining": ...}`. While starting or draining, a new session's WebSocket upgrade gets HTTP 503 before the handshake, so the gateway never tells a client `welcome` for a session that cannot run.

SIGTERM or SIGINT starts a drain: new sessions are refused, open ones keep working for up to `--drain-s` (25 s), and any left then get `session.ended{reason: "shutdown"}`. Every session's `finally` block settles its budget, and the process exits 0. In Docker the service runs with `init: true`, because Python as PID 1 would otherwise ignore SIGTERM, and `stop_grace_period: 35s`.

## Starting the orchestrator and its flags

Start it with `uv run python -m voicecore.server`. At start the server loads the Silero model, because loading it inside the first session stalls that session's mic frames. It also builds the docs index once and warms the embedding model with one query, and every session shares that index.

| Flag | Default | Meaning |
|---|---|---|
| `--providers` | `mock` | `live` uses Deepgram, OpenRouter and the `--tts` provider, and spends money |
| `--host`, `--port` | `127.0.0.1`, `8765` | listen address |
| `--trace-dir` | off | write one trace file per session |
| `--policy` | `eager` live, `fixed` mock | endpointing: `fixed`, `adaptive`, `asr_assisted` or `eager` |
| `--llm-model` | `openai/gpt-oss-120b` | OpenRouter model ID |
| `--llm-provider` | `Cerebras` | OpenRouter provider to try first; `any` lets OpenRouter route |
| `--llm-reasoning` | `low` | reasoning effort; `none` omits it |
| `--tts` | `deepgram` | live speech: `deepgram` (Aura-2) or `cartesia` (sonic-3.6) |

Mock mode keeps the fixed policy because the mock STT returns its canned final at every pause, which would end every turn early under eager endpointing. With a different `--llm-model`, the Cerebras pin and the low effort are dropped, but another provider or effort you pass still applies. Messages are limited to 1 MiB.

## Live providers need a budget reservation

Live adapters cost money, so `providers/factory.py` refuses to build one without a budget reservation from the right pool: `usd` for Deepgram (STT and TTS) and OpenRouter, `cartesia_credits` for Cartesia. `budget.py` writes each reservation to the ledger `benchmarks/spend_ledger.json` at once, under a file lock, so a crash before settling still counts the worst case against the cap.

| Pool | Project cap | Reserved per live session |
|---|---|---|
| `usd` | $5.00 | STT: 300 s of audio at $0.0077 per minute; LLM: $0.02; TTS with `--tts deepgram`: 4,000 characters, $0.12, reserved at the first answer |
| `cartesia_credits` | 16,000 credits | TTS with `--tts cartesia`: 1,500 characters, reserved at the first answer |

The adapters also enforce the per-session caps themselves, and each raises a fatal provider error:

- Deepgram refuses audio past 300 s, and the session says once that voice input has reached its limit; typed questions keep working.
- The LLM refuses a call whose worst-case cost would pass the reservation, and the session says it is having trouble answering.
- The TTS adapter refuses text past its cap, 4,000 characters for Deepgram Aura-2 or 1,500 for Cartesia. The answer arrives as text, and the session says once, as a text reply, that spoken replies have reached their limit.

When the session ends, `settle` replaces each reservation with the amount actually used.

## Why OnDemandTTS waits for the first answer

`OnDemandTTS` in `server.py` wraps the live TTS stream, Deepgram or Cartesia, so that its budget is reserved only when the session first speaks. An idle session that never asks a question does not hold $0.12 of the `usd` pool, or 1,500 Cartesia credits. A security review on 2026-10-30 asked for this.

It still opens the socket early. `warm()` opens the TTS WebSocket at session start, which costs nothing. On the first `synth()`, the wrapper builds the real `DeepgramTTS` or `CartesiaTTS` on that already-open socket and reserves the budget at that moment. If the reservation is refused, the error becomes a fatal TTS error and the session answers in text only.

The same wrapper serves the one TTS retry. The retry stream is a second `OnDemandTTS` that bills the same reservation and gets only what is left of the session's character cap, so a retry can never double the spend.

## How provider sockets are opened at session start

`Session.start()` calls `warm()` on every provider that has one, as background tasks, so the first turn does not pay for connection setup:

- **Deepgram** opens its streaming WebSocket. Deepgram closes a socket that gets no audio for 10 s, so the adapter sends `KeepAlive` every 4 s while no audio is sent.
- **OpenRouter** gets a free key-info request, `GET /key`, that opens the HTTPS connection. The process shares one connection pool with a 60 s keep-alive, because the httpx default of 5 s closed it while the user was talking.
- **Text-to-speech**, Deepgram Aura-2 or Cartesia, opens its WebSocket through `OnDemandTTS.warm()`, without reserving budget. If Deepgram closes that socket while it is idle, the next answer opens it again.

Pre-opening the Cartesia socket alone moved TTS first audio from p50 456 ms to p50 145 ms (live, n = 15 turns per run, `reports/latency_tuning.md`). With Deepgram Aura-2, also pre-opened, TTS first audio was p50 115 ms (live, n = 6). A failed warm-up is not fatal. The first real request connects again.

## The Session runtime tasks and queues

`runtime/session.py` holds one conversation. `start()` launches its long-lived tasks:

- one warm-up task per provider;
- the TTS reader, which turns synthesized audio into 20 ms agent frames;
- with STT, a sender that drains the STT queue, and a reader that collects partial and final transcripts.

Each generation runs in its own task, which streams the answer and feeds TTS. After an endpoint, a short task waits up to 5 s for STT to settle on a final. A paused client starts a 30 s timer that cancels the playing generation.

Mic audio reaches STT through a queue of 50 frames (1 s). When STT is slower than real time, the oldest audio is dropped and counted in `stt_drops`, so the floor logic is never blocked. Only speech is queued: a 300 ms pre-roll keeps the first syllable, and a 600 ms hangover lets `Finalize` see the whole turn. While the agent is playing, voiced frames are mostly its own echo, so STT opens only once the user takes the floor. `close()` cancels every task and closes the STT and TTS streams.

## How the floor and session states work

Each session has one `Floor`, configured with an endpoint policy. It sees every 20 ms frame with its VAD probability, its power, and the power of the agent audio the client was playing at that moment. It emits three kinds of events: `speech_started`, `barge_in` and `endpoint`.

The session moves through five states: listening, user speaking, thinking, speaking and ended.

- `speech_started` or `barge_in` opens a new turn, cancels any active generation and sends `user.speech_started`.
- `endpoint` moves to thinking, sends `Finalize` to STT once per pause, and starts the wait for the final transcript.
- The first agent frame of a generation moves to speaking. `playout.stopped{reason: "done"}` from the client moves back to listening.

If the user speaks again within 2.5 s of an endpoint, before the answer is audible, the session treats it as the same question. It cancels the early answer and answers the joined text once. See [turn-taking](../concepts/turn-taking.md) and [endpointing](../concepts/endpointing.md).

## How generations and the fence work in the runtime

A generation is one answer: its LLM stream, its TTS context and its audio. The session counts generations up by one each time, and its fence is the highest cancelled one. A generation is alive only while it is the newest, above the fence, and the session has not ended. Every step checks this before it acts: before sending text to TTS, before turning audio into a frame, and before streaming the next piece of the answer.

Starting a generation first cancels the active one with reason `superseded`. `cancel(g)` raises the fence, stops the generation's task, tells the TTS adapter to drop it, and sends `agent.cancel{gen}` so the gateway and the browser fence too. Cancel reasons in traces include `speech_started`, `barge_in`, `superseded`, `client_resumed` and `paused`.

Agent frames are 960 bytes, which is 20 ms at 24 kHz. The stream ID is the generation, sequences start at 0 per generation, and the last frame carries the end-of-stream flag. The session keeps the audio it sent per generation as the echo reference for the floor.

## How the runtime recovers from provider failures

Every turn ends with an answer and an end, even when a provider fails. Provider errors come in three kinds: retryable, rate limited and fatal. HTTP 429 is rate limited, other 4xx statuses are fatal, and the rest are retryable.

| Failure | What the session does |
|---|---|
| STT gives no text for the turn (waits up to 5 s) | answers "Sorry, could you say that again?" |
| LLM stream stalls for 8 s | speaks the reprompt after whatever was already said |
| LLM HTTP 429 before any text | waits 1, then 2, then 4 s and retries; then says it is busy |
| other LLM error | says it is having trouble answering |
| TTS error | still sends the text answer; retries once on a fresh stream if none of it was heard |
| STT cap reached | says voice input has reached its limit; typed questions keep working |
| STT stream drops | reconnects once after 0.2 s on a new stream with the same reservation and audio cap. If the turn had already ended, its partial transcript becomes final at once; otherwise the new stream hears the audio since the last final again (up to 10 s) |
| STT drops a second time | says voice input is unavailable and the microphone is ignored; typed questions keep working |
| client paused for 30 s | cancels the playing generation |
| the LLM part of a turn passes 20 s, even with tokens still trickling in | stops it and says it is having trouble answering; speech of an answer already written is never cut |
| the LLM circuit breaker is open | says it is busy without calling the provider |
| the STT circuit breaker is open when a session starts | says "Voice input is unavailable right now; you can type your question." once, ignores the microphone, answers typed questions |
| the TTS circuit breaker is open | answers in text and says once that spoken replies are unavailable |

The TTS retry is skipped after a fatal error, and it never repeats speech the user already heard.

**Circuit breakers.** Each orchestrator process keeps one breaker per provider kind (`stt`, `llm`, `tts`), shared by all its sessions (`voicecore/resilience.py`). Five retryable or rate-limited failures within 60 s open it, whatever succeeded in between, and for 30 s every call fails fast. Then one call goes out as a probe. Only the probe's success closes the breaker, so a session still streaming from before an outage cannot. The probe's failure, or 10 s without a verdict, opens it again, and a probe cancelled by a barge-in leaves the breaker open, never stuck. Fatal errors, such as a bad key or a session cap, and VoiceCore's own bugs are no verdict on the provider. The state is exported as `voicecore_breaker_state` (0 closed, 1 half-open, 2 open) and alerts as `BreakerOpen`.

## How the orchestrator traces a session

`trace.py` writes SPEC section 5 events. A `Tracer` per session stamps each event with the session ID, a span, an event name, `t_mono_us` and `process: "agent-core"`. With `--trace-dir`, a `JsonlSink` appends them to `{session_id}.jsonl`. The clock is the event loop's monotonic time, which lets tests run on fake time with looptime.

The tracer strips the `text`, `transcript` and `answer` attributes unless it was created with `include_text`, so transcripts and answers stay out of traces by default.

The runtime uses these spans: `turn` (speech_started, barge_in, endpoint, continuation), `stt` (final, turn_text), `llm` (request, first_token, stall, backoff, error), `tts` (first_audio, retry, error), `playout` (started, stopped, cancel_ack, from client events) and `runtime` (cancel, client_resumed). Every 250 mic frames, which is 5 s, it also writes a `clock` span `client_offset` event: the smallest gap seen between a frame's arrival and the end of its capture. The timeline uses it to put orchestrator events on the client's clock. See [trace events](../reference/trace-events.md).

## Mock mode and live mode

The orchestrator runs the same `Session` code in both modes. Only the providers change.

- **Mock** is the default, `--providers mock`. It costs nothing and needs no keys. The mock STT returns a canned question as a final on every `Finalize`. The mock LLM streams a fixed two-sentence answer, first token after 200 ms. The mock TTS synthesizes a 220 Hz tone, 60 ms per character, with first audio after 150 ms. The mocks are also the fault injector: their scripts add delays, errors and stalls.
- **Live** is `--providers live`. It uses Deepgram nova-3, `openai/gpt-oss-120b` with Cerebras first through OpenRouter at low reasoning effort, and Deepgram Aura-2 for speech, or Cartesia sonic-3.6 with `--tts cartesia`. It reserves budget per session and defaults to the eager endpoint policy.

A mock result shows mock behaviour only. Through the real gateway with mock providers, 40 concurrent sessions all completed, total p50 1,296 ms and p95 1,305 ms (mock, n = 40 sessions, one laptop). CPU was not profiled. Live concurrency was run only at 2 sessions, with Cartesia speech, the limit of its lowest plan tier. See [providers](../reference/providers.md).
