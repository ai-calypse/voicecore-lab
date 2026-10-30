# VoiceCore wire protocol, version 1

**Owner:** S01-T02. **Status:** v1, 2026-10-29. One protocol for both hops: browser ↔ Go gateway and Go gateway ↔ Python orchestrator. Golden vectors in [`vectors/`](vectors/) are the conformance test; the TypeScript (`ts/`), Go (`services/realtime-gateway/protocol`) and Python (`services/agent-core/voicecore/protocol.py`) codecs must all pass them.

Transport: one WebSocket per session per hop. Audio goes in **binary** messages (one frame per message). Control events go in **text** messages (one JSON object per message).

## 1. Audio frame

28-byte header, **big-endian**, then the payload.

| Offset | Field | Type | Meaning |
|---:|---|---|---|
| 0 | `version` | u8 | must be `1` |
| 1 | `kind` | u8 | `1` = mic PCM16 at 16 kHz; `2` = agent PCM16 at 24 kHz. Any other value is invalid |
| 2 | `flags` | u16 | bit 0 = `end_of_stream` (last frame of this stream or generation). Other bits must be 0 when sending and are ignored when receiving |
| 4 | `stream_id` | u32 | sender-chosen stream number, stable for one mic stream or one generation |
| 8 | `sequence` | u32 | starts at 0 per stream, +1 per frame |
| 12 | `capture_us` | u64 | sender monotonic clock in microseconds when the first sample was captured or produced. JSON vectors store it as a **string** (it can exceed 2^53) |
| 20 | `generation_id` | u32 | `0` for mic frames; the generation that produced an agent frame |
| 24 | `samples` | u16 | number of samples in the payload |
| 26 | `reserved` | u16 | send 0, ignore on receive |
| 28 | payload | `samples` × i16 | PCM16 **little-endian**, mono |

A frame is **invalid** when: it is shorter than 28 bytes; `version` ≠ 1; `kind` is not 1 or 2; or the payload length ≠ `samples × 2`. A receiver closes the WebSocket with code **1007** on an invalid frame.

Mic frames in a session are 20 ms (320 samples at 16 kHz) with `generation_id` 0; this is negotiated in `hello` and checked by the gateway (1007 otherwise), not by the codec.

## 2. Control events

JSON text messages with a `type` field. Fields listed below are **required**; receivers reject events with an unknown `type` or a missing required field, and ignore unknown extra fields. Times are microseconds on the sender's monotonic clock (`*_us`).

**Client → gateway** (the gateway forwards all except `hello` and `ping` to the orchestrator):

| `type` | Required fields | Meaning |
|---|---|---|
| `hello` | `version`, `token`, `mic{rate,frame_ms}`, `playout{rate}` | first message. Optional `session_id` plus `resume_key` (from `welcome`) resume that session |
| `ping` | `t_client_us` | heartbeat and clock-offset probe, every 2 s |
| `text.input` | `text` | typed user question |
| `mic.revoked` | — | the user stopped or lost the microphone; the session stays open for text |
| `client.paused` | — | the page is hidden or playout is paused |
| `client.resumed_playout` | — | playout resumed |
| `playout.started` | `gen`, `t_us` | first sample of generation `gen` was rendered |
| `playout.stopped` | `gen`, `reason`, `t_us` | `reason` is `done` or `cancel` |
| `cancel.ack` | `gen`, `played_until_seq` | the client flushed generation `gen`; last rendered frame sequence (−1 if none) |

**Gateway / orchestrator → client:**

| `type` | Required fields | Meaning |
|---|---|---|
| `welcome` | `session_id`, `resume_key`, `resume_window_ms`, `resumed` | reply to a valid `hello`. `session_id` is `s-<copy id>-<16 hex>`; `resume_key` (64 hex) is the only proof of ownership for a resume |
| `pong` | `t_client_us`, `t_server_us` | reply to `ping` (sent by the gateway) |
| `user.speech_started` | `turn_id` | floor: the user started speaking |
| `transcript.partial` | `turn_id`, `text` | interim transcript |
| `transcript.final` | `turn_id`, `text` | final transcript of a turn |
| `agent.generation_started` | `turn_id`, `gen` | a new generation began |
| `agent.text` | `gen`, `text` | answer text (also sent for voice turns) |
| `agent.cancel` | `gen` | stop and flush generation `gen` and every older one |
| `answer.sources` | `gen`, `sources[]` | citations: each `{id, url, title}` |
| `session.ended` | `reason` | `client`, `expired`, `budget`, `error`, `shutdown` |

**Gateway → orchestrator only:**

| `type` | Required fields | Meaning |
|---|---|---|
| `client.resumed` | — | the client reconnected within the resume window; the orchestrator cancels the live generation so nothing is spoken twice |

The orchestrator learns the session ID from the upstream URL `ws://<orchestrator>/v1/session/{session_id}`.

### Close codes

| Code | When |
|---:|---|
| 1000 | normal close |
| 1007 | invalid audio frame |
| 1008 | first message is not a valid `hello`, or an unknown/invalid event |
| 4001 | token invalid or expired |
| 4002 | unsupported `version` or audio format |
| 4003 | heartbeat missed (no message for 10 s) |
| 1013 | session limit reached (global or per client IP); try again later |
| 1011 | the gateway could not reach the orchestrator (`orchestrator unavailable`) |

## 3. Generation fencing

Every agent frame carries `generation_id`. When generation `g` is cancelled, each queue owner — the orchestrator's outbound queue, the gateway's send queue, and the browser playout — sets `fence = max(fence, g)` and drops every agent frame with `generation_id <= fence`, including frames already queued. Generation IDs increase by 1 per new generation in a session and never repeat. The gateway learns `g` from the `agent.cancel` event it forwards; the browser acknowledges with `cancel.ack`.

## 4. Session rules (gateway)

- `POST /v1/session` returns `{token}`, valid for 60 s (format below).
- The first message must be `hello` within 5 s. Bad or expired token → 4001. `version` ≠ 1, mic rate ≠ 16000, `frame_ms` ≠ 20 or playout rate ≠ 24000 → 4002.
- Mic frames per stream: `sequence` equal to the last one → dropped, counted `drops_duplicate`; lower → dropped, counted `drops_stale`; higher than last + 1 → forwarded, the missing count is added to `gaps`.
- The upstream queue holds at most 50 frames (1 s); when full the oldest frame is dropped and counted `drops_overload`. The client-bound queue holds at most 1,500 agent frames (30 s); overflow is counted `drops_overload_out`.
- No message from the client for 10 s → close 4003.
- Tokens: `POST /v1/session` returns `<expiry>.<nonce>.<HMAC(expiry.nonce.client IP)>`. A token starts **one** session, only from the IP it was minted for (4001 otherwise). A `hello` refused with 1013 or 1011 does not use it up. The client IP is the peer address, or `X-Forwarded-For` only through `-trusted-proxies`.
- Resume: a `hello` with the `session_id` and matching `resume_key` of a disconnected session within 10 s keeps the session (and its upstream connection). The token may already be spent then. A wrong or missing key, or a `hello` after the window, is a new session and needs an unused token: a spent one gets 4001, so the client fetches a fresh token. The resume fences the newest agent generation (audio queued while the client was away is dropped) and sends `client.resumed` upstream. Clients pick a random first `stream_id` so a resumed session never sees a reused stream.
- `GET /debug/counters` returns the counters and queue depth as JSON.
- Abuse limits (defaults; flags on `cmd/gateway`):
  - Requests whose `Host` is not allow-listed are refused with 421 (`localhost`, `127.0.0.1`, `::1`).
  - `POST /v1/session` is limited to 10 per minute per IP (429 beyond that).
  - At most 50 sessions in total and 4 per IP (beyond that, close 1013).
  - A session ends after 15 minutes (`session.ended{reason:"expired"}`).
  - Per connection, mic frames pass at real-time pace with a 2 s burst; more are dropped and counted in `drops_ratelimit`.
  - `text.input` events pass at 1 per second with a burst of 5; more are dropped.
  - `text.input.text` must be a string of at most 500 characters (close 1008 otherwise).
  - At most 256 client events may wait for the orchestrator (close 1008 beyond that).

## 5. Trace event

Every process writes JSON lines with this shape; one schema for the gateway, orchestrator, SDK and harness.

```json
{"trace_id": "s-1f2e", "span": "tts", "event": "first_audio", "t_mono_us": 1234567, "process": "agent-core", "generation_id": 3, "attrs": {}}
```

| Field | Required | Meaning |
|---|---|---|
| `trace_id` | yes | the session ID |
| `span` | yes | stage: `capture`, `gateway`, `turn`, `stt`, `llm`, `tts`, `playout`, `answer` |
| `event` | yes | what happened, for example `endpoint`, `final`, `first_token`, `first_audio`, `started`, `stopped` |
| `t_mono_us` | yes | the process's monotonic clock; the timeline aligns processes with ping/pong offsets |
| `process` | yes | `browser`, `gateway`, `agent-core`, `harness` |
| `generation_id` | no | when the event belongs to a generation |
| `attrs` | yes | extra numbers and labels. **No transcript or answer text** unless the run sets `include_text` |
