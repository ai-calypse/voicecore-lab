---
title: Realtime gateway
description: How the Go gateway owns each client connection, from session tokens and the hello handshake to bounded queues, the outbound fence, abuse limits and traces.
---

## What the Go gateway owns

The gateway in `services/realtime-gateway` owns the connection between the browser and the orchestrator. For every session it holds one browser WebSocket and one orchestrator WebSocket and moves frames and events between them. It does not understand speech or answers. It enforces the session rules in SPEC section 4:

- session tokens and the `hello` handshake;
- the heartbeat and the 10 s resume window;
- per-stream sequence checks, and bounded queues with drop counters;
- the outbound generation fence on agent audio;
- abuse limits: host allow-list, origin patterns, token rate, session caps and per-connection rates.

The code is in `session/server.go`, which has the HTTP routes, tokens, hello and limits, and `session/session.go`, which runs one session's goroutines and queues. `cmd/gateway/main.go` turns the defaults into command-line flags. The Go codec lives in `protocol/`, and its tests share the golden vectors with the TypeScript and Python codecs.

## How session tokens are issued and checked

`POST /v1/session` returns `{"token": "..."}`. The token has three parts separated by dots: the expiry time in Unix seconds, a random 16-hex nonce, and the hex HMAC-SHA256 of `expiry.nonce.client IP`, signed with the gateway's secret. It is valid for 60 s. When `hello` arrives, the gateway checks the signature with a constant-time comparison against the IP the WebSocket comes from, then marks the nonce as used. So a token:

- starts one session only; a second `hello` with it closes with 4001, but a `hello` refused with 1013 or 1011 does not use it up, so the client can retry with the same token;
- works only from the IP it was minted for;
- must be used within a minute.

Used nonces are kept in memory until their token would have expired anyway.

The client IP is the connection's peer address. `X-Forwarded-For` is believed only when the peer is inside one of the `-trusted-proxies` CIDRs, such as a load balancer; the gateway then takes the rightmost address in that header that is not itself a trusted proxy. With no trusted proxies, the header is ignored, so a client cannot pick its own IP.

The secret comes from the `GATEWAY_SECRET` environment variable. When it is unset, the gateway generates a random 32-byte secret at start, so tokens do not survive a restart.

:::warning
The token is not bound to a user, and the endpoint answers with `Access-Control-Allow-Origin: *`. Issuance is limited only by the per-IP rate of 10 tokens per minute and the host allow-list.
:::

## The hello and welcome handshake

`GET /v1/ws` upgrades to a WebSocket if the browser's origin matches the allowed patterns. The first message must be a text `hello` within 5 s. When it is not, or when the session cannot start, the gateway closes with a specific code:

| Problem | Close code |
|---|---|
| no message within 5 s, or the first message is not a valid `hello` | 1008 |
| token invalid or expired | 4001 |
| `version` not 1, mic rate not 16000, `frame_ms` not 20, or playout rate not 24000 | 4002 |
| session cap reached, in total or per IP | 1013 |
| the orchestrator cannot be dialled within 5 s | 1011 |

For a new session the gateway creates an ID, `s-<copy id>-` followed by 16 hex characters, for example `s-gw-3f9c2a1b7d4e6f80`. The copy id comes from `-copy-id` (default `gw`), so with several gateways a load balancer can send a resume to the copy that owns the session. The gateway also creates a resume key, 32 random bytes as 64 hex characters, and dials `<upstream>/v1/session/{id}`. It starts two goroutines that write to and read from the orchestrator, then sends `welcome{session_id, resume_key, resume_window_ms, resumed}`. A `hello` that carries the `session_id` and the matching `resume_key` of a detached session resumes that session instead.

## How the heartbeat closes silent clients

After `welcome`, every message from the client, binary or text, resets a 10 s watchdog. If the watchdog fires, the gateway closes the connection with code 4003, "heartbeat missed". The SDK sends `ping` every 2 s, so a client has to miss five pings in a row before it is closed. Mic frames reset the watchdog too.

The gateway answers each `ping` itself and does not forward it to the orchestrator. The `pong` echoes the client's `t_client_us` and adds `t_server_us`, the gateway's monotonic clock in microseconds since it started. The pong is pushed to the front of the client-bound queue, ahead of any queued agent audio, so a backlog of audio does not delay it.

This keeps the clock offset honest. The client computes the offset from the round trip, and a pong that waited behind audio would make the round trip look longer than the network is.

## How the resume window keeps a session alive

A session outlives its client connection. When the client disappears without a normal close, the gateway keeps the session and its orchestrator socket open for 10 s, the resume window. A close with code 1000 or 1001, or a protocol violation, ends the session at once instead.

To resume, the client sends `hello` with its `session_id` and `resume_key` inside the window. The key is compared in constant time and only the client that received `welcome` has it, so knowing a session id is not enough to take over someone's session. A resume does not use up a token: the token in that `hello` may already be spent by the original session. A wrong or missing key gets a new session instead, which needs an unused token. The key is never logged or traced. Before it sends `welcome`, the gateway:

1. raises its outbound fence to the newest generation it has seen, and purges that audio from the client-bound queue, so speech queued while the client was away is not played;
2. sends `client.resumed` upstream, and the orchestrator cancels the live generation so nothing is spoken twice.

The order matters. Once the client has `welcome`, a new generation may already be on its way and must not be caught by this fence; fencing later showed up as a test flake. After 10 s, a `hello` with the old ID is a new session and needs an unused token. Clients pick a random first stream ID, so a resumed session never sees a reused mic stream.

## How mic frames are checked

Every binary message from the client must decode as a mic frame with exactly 320 samples and `generation_id` 0. Anything else, including a truncated header or a payload of the wrong length, closes the connection with 1007. Valid frames then pass the per-stream sequence rules:

| Sequence compared with the last one on this stream | Action | Counter |
|---|---|---|
| equal | dropped | `drops_duplicate` |
| lower | dropped | `drops_stale` |
| higher than last + 1 | forwarded | missing count added to `gaps` |
| first frame of a stream, above 0 | forwarded | starting sequence added to `gaps` |

After `mic.revoked`, every stream seen so far is marked revoked, and its later frames are dropped and counted as stale. The session stays open for text. There is no reorder buffer: one WebSocket runs over TCP, which cannot reorder frames, so the gateway only counts what it sees. It does not handle 32-bit sequence wrap; a code note says that takes 2.7 years of 20 ms frames.

## How the bounded queues drop audio

Each session has two queues, and both treat audio and events differently. Audio is droppable: when a queue's audio is at its cap, the oldest audio frame is removed and counted. Events are never dropped.

| Queue | Holds | Cap | When full |
|---|---|---|---|
| upstream, to the orchestrator | mic frames and client events | 50 frames (1 s), 256 events | oldest frame dropped, `drops_overload`; an event over the cap closes the client with 1008 |
| client-bound, to the browser | agent frames and events | 1,500 frames (30 s) | oldest frame dropped, `drops_overload_out` |

Writes to the client time out after 10 s. When a write fails, the item goes back to the front of the queue, so a resumed connection receives it. A failed write to or read from the orchestrator ends the session with reason `error`.

Queue depths, in audio frames, are exposed as `depth` and `depth_out` at `GET /debug/counters`. In the transport benchmark no queue dropped anything: 0 drops and 0 gaps at 1 and at 20 streams (fake-provider, loopback, 10 s per run).

## How the outbound fence drops cancelled audio

The gateway is one of the three fence owners in SPEC section 3. It reads every message from the orchestrator. When an `agent.cancel{gen}` passes through, the gateway:

- raises its fence to at least `gen`;
- purges every queued agent frame at or below the fence from the client-bound queue, and adds the count to `drops_fenced`;
- writes a `fence` trace event with `dropped_queued`;
- forwards the event to the client.

Agent frames that arrive later with a generation at or below the fence are dropped on arrival and counted in `drops_fenced` too. The gateway also remembers the newest generation it has seen. That is the generation it fences on resume, and it traces `agent_first_frame` for the first frame of each new, unfenced generation.

Apart from resume, the gateway never decides to cancel by itself. It learns cancellations from the orchestrator, and the browser playout applies the same rule one hop later. The test `TestAgentFramesAtOrBelowFenceAreNotSent` covers this path.

## The debug counters endpoint

`GET /debug/counters` returns one JSON object with counters summed across all sessions since the gateway started. It is the quickest way to see whether the gateway dropped anything during a run. `cmd/wsload` and the WSS runner in `harness/runner/wss.py` read it to report gateway drops and gaps, The endpoint has no authentication, but the host allow-list still applies.

| Key | Meaning |
|---|---|
| `sessions` | live sessions |
| `depth`, `depth_out` | audio frames queued towards the orchestrator and towards clients |
| `drops_duplicate`, `drops_stale` | mic frames dropped by the sequence rules or after `mic.revoked` |
| `gaps` | mic frames missing between received sequence numbers |
| `drops_overload`, `drops_overload_out` | audio dropped because a queue was full |
| `drops_ratelimit` | mic frames or `text.input` events over the per-connection rate |
| `drops_fenced` | agent frames dropped by the generation fence |

## Abuse limits on sessions and tokens

The gateway's defaults assume a local development machine. A security review on 2026-10-30 added limits that protect the paid providers behind it, and each one has a flag on `cmd/gateway`.

- **Host allow-list.** A request whose `Host` header is not `localhost`, `127.0.0.1` or `::1` gets HTTP 421. A DNS-rebinding page arrives with its own host name, so this blocks it.
- **Origins.** The WebSocket upgrade only accepts browser origins that match `localhost:*` or `127.0.0.1:*`.
- **Token rate.** `POST /v1/session` allows 10 tokens per minute per client IP, as a token bucket with a burst of 10. Beyond that it answers HTTP 429.
- **Session caps.** At most 50 sessions in total and 4 per client IP. A slot is reserved before the orchestrator is dialled, so concurrent hellos cannot overshoot the cap. Beyond it, the socket closes with 1013.
- **Session age.** A session ends after 15 minutes with `session.ended{reason: "expired"}`.

## Per-connection rate limits on frames and text

Inside one connection the gateway applies these limits, so a single client cannot push the voice pipeline behind it faster than real time:

- **Mic frames** pass at real-time pace, 50 frames per second, with a burst of 100 frames (2 s). Extra frames are dropped and counted in `drops_ratelimit`; otherwise the VAD and STT behind the gateway would pay for them.
- **Typed questions.** `text.input` events pass at 1 per second with a burst of 5. Extra ones are dropped and counted in the same counter.
- **Text size.** `text.input.text` must be a string of at most 500 characters. Anything else, such as a list of content parts, closes the connection with 1008, because the text goes into an LLM prompt and its history.
- **Message size.** A single client message may be at most 64 KiB. Messages from the orchestrator may be up to 1 MiB.

Unknown event types also close with 1008. After `hello`, the gateway accepts only the client events that SPEC section 2 lists.

## Gateway trace events

Start the gateway with `-trace FILE` and it appends SPEC section 5 trace events to that file as JSON lines. Each event has `process` and `span` set to `gateway`, and `t_mono_us` on the gateway's monotonic clock, the same clock as `t_server_us` in pongs. The gateway traces no text.

| Event | When | Attributes |
|---|---|---|
| `session_started` | the orchestrator socket is open | none |
| `client_attached` | a client connection takes the session | `resumed` |
| `client_detached` | that connection ended | `ends_session` |
| `agent_first_frame` | the first frame of a new, unfenced generation arrives | generation ID |
| `fence` | `agent.cancel` passed through | `dropped_queued`, generation ID |
| `session_ended` | the session ended | `reason` |

Because pongs and traces share one clock, `harness/session_timeline.py` can move gateway events onto the client's clock with the ping and pong offset.

## Gateway command-line flags

Run `go run ./cmd/gateway` in `services/realtime-gateway`. Every limit flag accepts 0 to turn the limit off, and an empty `-hosts` allows any host.

| Flag | Default | Meaning |
|---|---|---|
| `-addr` | `127.0.0.1:8080` | listen address |
| `-upstream` | `ws://127.0.0.1:8765` | orchestrator base URL |
| `-origins` | `localhost:*,127.0.0.1:*` | allowed browser origins |
| `-hosts` | `localhost,127.0.0.1,::1` | allowed Host header names |
| `-trace` | off | append trace events to this file |
| `-max-sessions` | 50 | live sessions in total |
| `-max-sessions-per-ip` | 4 | live sessions per client IP |
| `-tokens-per-minute` | 10 | session tokens per client IP per minute |

The other values are fixed in `session.Defaults`: token TTL 60 s, hello timeout 5 s, heartbeat 10 s, resume window 10 s, queue caps of 50 and 1,500 frames, session age 15 minutes, 500 text characters and 256 queued events. `GATEWAY_SECRET` sets the token secret.

## How much latency the gateway adds

The transport benchmark in `benchmarks/transport.md` measures the gateway with `cmd/wsload` and the `cmd/fakeorch` echo orchestrator, on one Apple M4 laptop over loopback, labelled `fake-provider`. Each stream sends one 20 ms mic frame every 20 ms for 10 s, and fakeorch echoes it back as 24 kHz agent audio.

| Path | Streams | RTT p50 / p95 / p99 |
|---|---:|---|
| straight to fakeorch | 1 | 0.24 / 0.37 / 0.43 ms |
| through the gateway | 1 | 0.43 / 0.60 / 0.69 ms |
| through the gateway | 20 | 1.08 / 1.68 / 2.16 ms |

Both gateway passes together add 0.19 ms at the median (fake-provider, loopback, n = 500 frames), about 0.1 ms per pass. No run dropped a frame or saw a gap. In Go benchmarks, decoding one 20 ms mic frame takes 205.7 ns with one allocation, and encoding one agent frame takes 250.1 ns. Real packet loss was not measured, because it needs kernel shaping with `sudo`.

## How the gateway reports health and shuts down gracefully

`GET /healthz` answers 200 `{"status": "ok", "version": ...}` while the process is alive. `GET /readyz` answers 200 `{"ready": true}`, or 503 `{"ready": false, "draining": true}` once a drain has begun, so a load balancer stops sending new users. The image is distroless, with no curl, so the container healthcheck runs the binary itself: `/gateway -probe http://127.0.0.1:8080/readyz` exits 0 on HTTP 200 and 1 otherwise.

On SIGINT or SIGTERM the gateway drains instead of cutting calls off. New tokens get HTTP 503 and new sessions close with 1013 `draining`, while open sessions keep working, and a client that reconnects within the resume window can still resume. After `-drain` (25 s by default) the remaining sessions end with `session.ended{reason: "shutdown"}`, then the HTTP server shuts down and the process exits 0.

