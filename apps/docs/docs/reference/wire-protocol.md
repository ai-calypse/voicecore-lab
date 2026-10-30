---
title: Wire protocol
description: The VoiceCore wire protocol version 1, with the audio frame header, payload format, every control event per direction, the generation fencing rule, close codes, session rules and the trace event schema.
---

This page is the reference for VoiceCore wire protocol version 1, as specified in `packages/protocol/SPEC.md`. The golden vectors in `packages/protocol/vectors/` are the conformance test: the TypeScript codec (`packages/protocol/ts/`), the Go codec (`services/realtime-gateway/protocol`) and the Python codec (`services/agent-core/voicecore/protocol.py`) must all pass them.

## One protocol for both hops

VoiceCore uses the same protocol on both network hops: browser to Go gateway, and Go gateway to Python orchestrator.

- **Transport:** one WebSocket per session per hop.
- **Audio:** binary WebSocket messages, one audio frame per message.
- **Control events:** text WebSocket messages, one JSON object per message.

A browser session starts with `POST /v1/session` on the gateway, which returns `{token}`. The client then opens the WebSocket at `/v1/ws` and sends `hello` with that token as its first message. For each session, the gateway opens its own WebSocket to the orchestrator at `ws://<orchestrator>/v1/session/{session_id}`. The orchestrator learns the session id from that URL path.

Because both hops speak the same protocol, the gateway forwards most events unchanged. It handles `hello` and `ping` itself, and adds one event of its own, `client.resumed`, towards the orchestrator.

## Audio frame header fields

Every audio frame starts with a 28-byte header in big-endian byte order, followed by the payload. The same header is used for microphone audio going up and agent audio coming down. One WebSocket binary message carries exactly one frame, so no length prefix is needed: the receiver reads the header, then checks that the rest of the message matches the `samples` field.

| Offset | Field | Type | Notes |
|---:|---|---|---|
| 0 | `version` | u8 | must be `1` |
| 1 | `kind` | u8 | `1` = mic PCM16 at 16 kHz; `2` = agent PCM16 at 24 kHz; any other value is invalid |
| 2 | `flags` | u16 | bit 0 = `end_of_stream`, the last frame of this stream or generation; other bits must be 0 when sending and are ignored when receiving |
| 4 | `stream_id` | u32 | chosen by the sender, stable for one mic stream or one generation |
| 8 | `sequence` | u32 | starts at 0 per stream, +1 per frame |
| 12 | `capture_us` | u64 | sender's monotonic clock in microseconds when the first sample was captured or produced |
| 20 | `generation_id` | u32 | `0` for mic frames; for agent frames, the generation that produced the frame |
| 24 | `samples` | u16 | number of samples in the payload |
| 26 | `reserved` | u16 | send 0, ignore on receive |
| 28 | payload | `samples` × i16 | PCM16 little-endian, mono |

Note the two byte orders: the header is big-endian, the PCM payload is little-endian.

## Audio payload format and frame sizes

The payload after the 28-byte header is mono PCM16, little-endian, with exactly `samples` × 2 bytes.

- **Mic frames** (`kind` 1) are 16 kHz and always 20 ms long: 320 samples, 640 payload bytes, 668 bytes in total with the header. Their `generation_id` is 0. The 20 ms frame length is negotiated in `hello` and enforced by the gateway, not by the codec.
- **Agent frames** (`kind` 2) are 24 kHz. The orchestrator cuts TTS audio into 20 ms frames of 480 samples (960 bytes). The last frame of a generation can be shorter, even empty, and carries the `end_of_stream` flag.
- **`capture_us`** is the time on the sender's clock. For mic frames that is the client's capture time of the first sample, which lets the orchestrator place its endpoint decision on the client's clock. For agent frames it is the orchestrator's clock when it sent the frame.

The JSON golden vectors store `capture_us` as a string, because a u64 can exceed 2^53 and would lose precision as a JSON number.

## When an audio frame is invalid

A receiver must treat an audio frame as invalid when any of these is true:

- the message is shorter than 28 bytes;
- `version` is not 1;
- `kind` is not 1 or 2;
- the payload length is not `samples` × 2.

On an invalid frame, the receiver closes the WebSocket with code **1007**.

Session-level rules are separate from codec validity. The codec accepts a mic frame of any length, but in a session every mic frame must be 20 ms (320 samples at 16 kHz) with `generation_id` 0. The gateway checks that and also closes with 1007 when it is broken. Unknown `flags` bits are not an error: senders must leave them at 0, and receivers ignore them.

## Control event rules

Control events are JSON objects in WebSocket text messages. Every event has a `type` field.

- The fields listed for each event type are **required**.
- A receiver **rejects** an event with an unknown `type` or a missing required field.
- A receiver **ignores** unknown extra fields, so a sender may add fields without breaking older receivers.
- Times are microseconds on the sender's monotonic clock, in fields named `*_us`.

At the gateway, an event that cannot be parsed, or a first message that is not a valid `hello`, closes the connection with code 1008. The `text` of `text.input` must be a string of at most 500 characters, or the gateway also closes with 1008.

The event tables on this page list every event type in protocol version 1, grouped by direction: client to gateway, gateway or orchestrator to client, and gateway to orchestrator.

## Client to gateway events

These are the events a client sends to the gateway, the browser SDK or any other client. The gateway forwards every client event to the orchestrator except `hello` and `ping`, which it handles itself. Times in `t_us` and `t_client_us` are on the client's own monotonic clock.

| `type` | Required fields | Meaning |
|---|---|---|
| `hello` | `version`, `token`, `mic{rate,frame_ms}`, `playout{rate}` | first message; optional `session_id` plus `resume_key` resume that session |
| `ping` | `t_client_us` | heartbeat and clock-offset probe, every 2 s |
| `text.input` | `text` | a typed user question |
| `mic.revoked` | none | the user stopped or lost the microphone; the session stays open for text |
| `client.paused` | none | the page is hidden or playout is paused |
| `client.resumed_playout` | none | playout resumed |
| `playout.started` | `gen`, `t_us` | the first sample of generation `gen` was rendered |
| `playout.stopped` | `gen`, `reason`, `t_us` | `reason` is `done` or `cancel` |
| `cancel.ack` | `gen`, `played_until_seq` | the client flushed generation `gen`; the last rendered frame sequence, or −1 if none |

The browser SDK sends `hello` with `version` 1, `mic` rate 16000 and `frame_ms` 20, and `playout` rate 24000, the only values the gateway accepts.

## Gateway and orchestrator to client events

These events reach the client. The gateway sends `welcome`, `pong` and its own `session.ended`; the orchestrator sends the rest, and the gateway forwards them. The orchestrator also sends `session.ended` with reason `budget` when it refuses a live session.

| `type` | Required fields | Meaning |
|---|---|---|
| `welcome` | `session_id`, `resume_key`, `resume_window_ms`, `resumed` | reply to a valid `hello`; `session_id` is `s-<copy id>-<16 hex>`, and `resume_key` (64 hex) is the proof needed to resume |
| `pong` | `t_client_us`, `t_server_us` | reply to `ping`, sent by the gateway |
| `user.speech_started` | `turn_id` | turn-taking: the user started speaking |
| `transcript.partial` | `turn_id`, `text` | interim transcript |
| `transcript.final` | `turn_id`, `text` | final transcript of a turn |
| `agent.generation_started` | `turn_id`, `gen` | a new generation began |
| `agent.text` | `gen`, `text` | answer text, also sent for voice turns |
| `agent.cancel` | `gen` | stop and flush generation `gen` and every older one |
| `answer.sources` | `gen`, `sources[]` | citations, each `{id, url, title}` |
| `session.ended` | `reason` | `client`, `expired`, `budget`, `error` or `shutdown` |

`agent.text` arrives for voice turns too, so a client can show the answer as text while it plays. `answer.sources` lists the passages the answer cites; each `url` is the page and section the citation opens.

## Gateway to orchestrator event

One event exists only on the gateway-to-orchestrator hop:

| `type` | Required fields | Meaning |
|---|---|---|
| `client.resumed` | none | the client reconnected within the resume window; the orchestrator cancels the live generation so nothing is spoken twice |

The gateway sends `client.resumed` when a client sends `hello` with the `session_id` and `resume_key` of a session that disconnected less than 10 s ago. The gateway keeps the session and its upstream connection open during that window. The orchestrator answers by cancelling the generation that was playing, because the audio queued while the client was away is lost and must not be replayed later. All other orchestrator input is either a forwarded client event or a mic frame.

## Generation fencing rule

Every agent frame carries a `generation_id`. Generation ids increase by 1 for each new generation in a session and never repeat.

When generation `g` is cancelled, each owner of an agent audio queue applies the same rule:

1. set `fence = max(fence, g)`;
2. drop every agent frame with `generation_id <= fence`, including frames that are already queued.

There are three queue owners: the orchestrator's outbound queue, the gateway's send queue towards the client, and the browser playout. The orchestrator fences first and sends `agent.cancel` with `gen`. The gateway reads `g` from that event as it forwards it, fences its own queue, and counts the dropped frames in `drops_fenced`. The browser applies the cancel to its playout and acknowledges with `cancel.ack`, reporting the last frame sequence it rendered (−1 when none).

Because the rule is "at or below the fence", a late frame from any cancelled generation is dropped wherever it arrives, even if the cancel and the frame cross on the network.

## WebSocket close codes

These are the WebSocket close codes of protocol version 1. The code tells a client what went wrong: 1013 means try again later, and 4001 means the token was bad or expired, so a new attempt needs a fresh token from `POST /v1/session`.

| Code | When |
|---:|---|
| 1000 | normal close |
| 1007 | invalid audio frame |
| 1008 | first message is not a valid `hello`, or an unknown or invalid event |
| 4001 | token invalid or expired |
| 4002 | unsupported `version` or audio format |
| 4003 | heartbeat missed: no message from the client for 10 s |
| 1013 | session limit reached, globally or per client IP; try again later |
| 1011 | the gateway could not reach the orchestrator; the close reason is `orchestrator unavailable` |

Codes 1000, 1007, 1008, 1011 and 1013 are standard WebSocket codes. The 4000-range codes are VoiceCore's own. When the gateway itself ends a session, for example after the 15-minute limit, it first sends `session.ended` with the reason, then closes.

## Session token and hello rules

The gateway enforces these rules at the start of every session:

- `POST /v1/session` returns `{token}`: `<expiry>.<nonce>.<HMAC-SHA256 of expiry.nonce.client IP>`, valid for 60 s. The secret comes from `GATEWAY_SECRET`, or is random per gateway process when that is unset.
- A token starts one session, from the IP it was minted for. Reusing it, or using it from another IP, closes with 4001. A `hello` refused with 1013 or 1011 does not use it up. The client IP comes from `X-Forwarded-For` only when the peer is a `-trusted-proxies` address.
- The first WebSocket message must be `hello`, within 5 s.
- A bad, expired, already used or wrong-IP token closes the connection with 4001.
- `version` other than 1, mic rate other than 16000, `frame_ms` other than 20, or playout rate other than 24000 closes it with 4002.
- After `hello`, no message from the client for 10 s closes the connection with 4003. The SDK's `ping` every 2 s keeps it alive.

The `pong` reply carries the client's own `t_client_us` back plus the gateway's `t_server_us`, so the client can estimate the clock offset to the gateway.

## Mic frame sequence and queue rules

The gateway checks each mic stream's `sequence` numbers and bounds its queues:

- `sequence` equal to the last one: the frame is dropped and counted as `drops_duplicate`.
- `sequence` lower than the last one: dropped, counted as `drops_stale`.
- `sequence` higher than last + 1: forwarded, and the number of missing frames is added to `gaps`.
- The queue towards the orchestrator holds at most 50 frames (1 s). When it is full, the oldest frame is dropped and counted as `drops_overload`.
- The queue towards the client holds at most 1,500 agent frames (30 s). Overflow is counted as `drops_overload_out`.

`GET /debug/counters` returns these counters as JSON, summed across sessions, together with `drops_ratelimit`, `drops_fenced`, the number of live `sessions`, the current queue depths `depth` and `depth_out`, `tokens_issued`, and the refusals before a session starts: `rejected_ratelimit`, `rejected_host`, `rejected_upgrade` (mostly a disallowed origin), `rejected_draining`, `rejected_token` (a bad, expired, reused or wrong-IP token at `hello`), `rejected_busy` (a session cap) and `rejected_upstream` (the orchestrator was not ready or could not be dialled). The `-admin-addr` listener serves the same counters, and Prometheus `/metrics` with `gateway_drops_total{reason}`, `gateway_rejected_total{reason}`, `gateway_gaps_total`, `gateway_tokens_issued_total` and `gateway_sessions`.

## Session resume after a disconnect

A client that loses its WebSocket can resume its session for 10 s:

- It sends `hello` with the `session_id` and `resume_key` from its earlier `welcome`. The token in that `hello` may already be spent; the key is the proof of ownership.
- A wrong or missing key does not resume. The `hello` is then treated as a new session and needs an unused token.
- The gateway keeps the session, and its upstream connection to the orchestrator, during that window.
- On resume, the gateway fences the newest agent generation, so audio queued while the client was away is dropped, and sends `client.resumed` upstream. The orchestrator cancels the live generation.
- The reply is `welcome` with `resumed: true`.

After the 10 s window, the session ends with reason `expired`, and a later `hello` is a new session that needs an unused token.

Clients pick a random first `stream_id`, so a resumed session never sees a stream id that the gateway has already seen. Otherwise, the duplicate and stale checks on `sequence` could drop the new stream's first frames.

## Gateway abuse limits

The gateway applies these limits by default. The Host list, the token rate and the two session limits have flags on `cmd/gateway`; the others are fixed in code (see [Configuration](configuration.md)):

- Requests whose `Host` header is not allow-listed are refused with HTTP 421. The default list is `localhost`, `127.0.0.1` and `::1`, which blocks DNS rebinding.
- `POST /v1/session` is limited to 10 per minute per client IP, with HTTP 429 beyond that.
- At most 50 sessions in total and 4 per client IP; beyond that, the WebSocket closes with 1013.
- A session ends after 15 minutes, with `session.ended` reason `expired`.
- Per connection, mic frames pass at real-time pace with a 2 s burst. Extra frames are dropped and counted in `drops_ratelimit`.
- `text.input` events pass at 1 per second with a burst of 5; more are dropped.
- `text.input` text must be a string of at most 500 characters, or the connection closes with 1008.
- At most 256 client events may wait for the orchestrator; beyond that, the connection closes with 1008.

## Trace event schema

Trace events are JSON lines in one shared shape, section 5 of the spec. The gateway and the orchestrator write them directly. The harness converts the headless client's log into the same shape when it merges a session timeline.

```json
{"trace_id": "s-1f2e", "span": "tts", "event": "first_audio", "t_mono_us": 1234567, "process": "agent-core", "generation_id": 3, "attrs": {}}
```

- `trace_id` (required) is the session id.
- `span` (required) is the stage, for example `capture`, `gateway`, `turn`, `stt`, `llm`, `tts` or `playout`.
- `event` (required) is what happened, for example `endpoint`, `final`, `first_token` or `first_audio`.
- `t_mono_us` (required) is the process's own monotonic clock. A timeline aligns processes with clock offsets.
- `process` (required) names the writer, for example `gateway` or `agent-core`.
- `generation_id` (optional) is set when the event belongs to a generation.
- `attrs` (required) holds extra numbers and labels. It carries **no transcript or answer text** unless the run sets `include_text`.

Every event each process emits is listed in [Trace events](trace-events.md).
