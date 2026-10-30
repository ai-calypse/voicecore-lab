---
title: Browser SDK
description: How the TypeScript SDK captures the microphone, talks to the gateway, plays agent audio behind a generation fence, and runs headless in Node for benchmarks.
---

## What the browser SDK owns

The browser SDK in `packages/web-sdk` owns the audio devices. It has three parts, all exported from `src/index.ts`:

- **Capture** (`src/capture/`) asks for the microphone, then emits 20 ms PCM16 frames at 16 kHz. Nothing is captured before the user grants consent.
- **VoiceClient** (`src/client.ts`) runs one WebSocket session with the gateway. It sends `hello`, mic frames and pings, and receives events and agent frames.
- **Playout** (`src/playout/`) plays 24 kHz agent audio in order, behind a generation fence, and emits playout events.

The same client and playout code also run in Node as the headless client in `bin/headless-client.ts`, which the benchmarks use. The SDK holds no provider keys. The page gets a short-lived session token from the gateway's `POST /v1/session` and passes it to the client. The demo widget in `apps/demo/src/widget.ts` is the reference integration.

## How capture gets audio off the microphone

`startCapture` calls `getUserMedia` for one channel, with echo cancellation, noise suppression and automatic gain control turned on. It then creates an `AudioContext` at the device's own sample rate and resumes it, because the user gesture may have expired while the permission prompt was open.

A small AudioWorklet processor named `vc-capture` is loaded from a Blob URL, so no bundler step is needed. Its only job is to copy each 128-sample render quantum of channel 0 and post it to the main thread. Resampling, PCM conversion and framing then happen on the main thread, in that order.

Each frame's `capture_us` comes from the sample count, not from the time the frame was sent. The start time is the arrival of the first block minus that block's duration, and frame k is stamped start plus 20,000 × k microseconds. The function returned by `startCapture` stops the tracks and closes the context.

:::note
Because blocks cross to the main thread before frames are cut, frames leave in small bursts: a 29.53 ms p95 interarrival (measured, loopback, n = 500 frames). See [WebSocket vs WebRTC](websocket-vs-webrtc.md).
:::

## How the resampler converts to 16 kHz

`Resampler` in `src/capture/resample.ts` turns any input rate into 16 kHz with a streaming windowed-sinc low-pass filter. The kernel has 64 taps with a Hann window. The cutoff is 0.4375 times the lower of the two rates, which is 7 kHz for a 16 kHz output. The filter is evaluated at fractional input positions, so 44.1 kHz input works as well as 48 kHz.

The resampler keeps its history between calls, so the output does not depend on how the input was chunked. Its delay is 32 input samples, and it is deterministic. Tests in `capture.test.ts` pin the behaviour:

- 4,800 samples at 48 kHz become 1,600, and 4,410 samples at 44.1 kHz become 1,600, also when pushed in 128-sample chunks.
- A 1 kHz sine at 48 kHz keeps 2,000 zero crossings per second, within 1 %.
- A 9 kHz tone, above the 8 kHz Nyquist limit of the output, is attenuated by at least 20 dB.

## The PCM16 conversion rule

`floatToPcm16` in `src/capture/pcm.ts` converts Web Audio floats to signed 16-bit samples with one rule. First clamp the sample to the range −1 to 1. Then round s × 32768 for a negative sample and s × 32767 for any other. The asymmetric scale uses the full PCM16 range, −32,768 to 32,767, without overflowing at +1.

The test pins the rule with exact values:

| Float in | PCM16 out |
|---|---|
| 0.5 | 16384 (0x4000) |
| 1.5 | 32767 (0x7FFF), clamped |
| −1.5 | −32768 (−0x8000), clamped |
| 0 | 0 |

The converted samples then go to the framer. On the wire they are written little-endian after the 28-byte frame header, as the protocol requires for every audio payload.

## How the framer cuts 20 ms frames

`Framer` in `src/capture/framer.ts` cuts the 16 kHz PCM16 stream into fixed frames of 320 samples, which is 20 ms. It keeps leftover samples for the next call and numbers frames from 0. For example, 330 samples give one frame with sequence 0 and keep 10 samples back. A further 630 samples then give frames 1 and 2.

The SDK always sends 20 ms frames because the protocol negotiates it. `hello` declares `mic.rate` 16000 and `mic.frame_ms` 20, and the gateway closes the socket with 1007 when a mic frame does not carry exactly 320 samples. Each mic frame goes out with kind 1, `generation_id` 0, the frame's sequence number, its `capture_us`, and the client's current stream ID.

## How VoiceClient opens a session

`VoiceClient` wraps one WebSocket to the gateway. You construct it with the WebSocket URL and a token from `POST /v1/session`, which is valid for 60 s. `connect()` opens the socket in `arraybuffer` binary mode and sends `hello` as soon as it opens:

```json
{"type": "hello", "version": 1, "token": "...", "mic": {"rate": 16000, "frame_ms": 20}, "playout": {"rate": 24000}}
```

To resume, the client adds the `session_id` and `resume_key` it was given. `connect()` resolves with the gateway's `welcome`, which carries `session_id`, `resume_key`, `resume_window_ms` and `resumed`. The client keeps both in memory only, so calling `connect()` again on the same object resumes the same session.

The client also reconnects by itself. When the socket closes unexpectedly after `welcome`, `onEvent` sees `socket.reconnecting`, and the client retries after 0.5, 1, 2, 4 and 4 s (`retryDelaysMs`), which outlasts the gateway's 10 s resume window. Policy closes (1007, 1008, 4002) are not retried. Each retry goes to `/v1/ws?resume=<session id>`, so a load balancer can send it to the gateway copy that owns the session, and resumes with the key. If a retry is refused with 4001, because the resume window passed and the token is already spent, the client asks the `getToken` option for a fresh one. The microphone keeps capturing across the gap, and frames sent while the socket is down are dropped. Only after the last failed attempt does `onEvent` see `socket.closed`. `close()` stops any retry for good. A `welcome` with `resumed: false` after a retry means a new session: the app should say so.

`startMic()` starts capture and sends frames as they come, under a new stream ID each time. The first stream ID is random, so a new client resuming a session never reuses a stream ID the gateway already saw. `stopMic()` stops capture and sends `mic.revoked`. `close()` closes with code 1000, which ends the session at the gateway.

## How ping and pong measure the clock offset

After `welcome`, the client sends `ping` with `t_client_us` every 2 s. The gateway answers with `pong`, which echoes `t_client_us` and adds its own `t_server_us`. When the pong arrives at local time now, the client computes:

```text
offsetUs = t_server_us - (t_client_us + now) / 2
```

This is the server clock minus the midpoint of the round trip, the NTP-style estimate. `offsetUs` is NaN until the first pong arrives. The gateway puts each pong at the front of its client-bound queue, so queued agent audio does not delay it.

The pings double as the heartbeat. The gateway closes a connection with 4003 when no message arrives for 10 s. The client's clock is `performance.now()` in microseconds unless you pass `nowUs`. The harness timeline uses the same ping and pong records, choosing the exchange with the smallest round trip, to put gateway traces on the client's clock.

## Events the client delivers to your app

`VoiceClient` has two callbacks. `onEvent` receives every decoded control event, including `welcome` and `pong`. `onAgentFrame` receives every decoded agent audio frame.

If you set `client.playout`, the client feeds it before your callbacks run:

- each agent frame goes to `playout.push` with its generation, sequence, samples and end-of-stream flag;
- `agent.cancel` goes to `playout.cancel` before `onEvent` sees it, so stale audio is already flushed when your app reacts.

When the socket closes, the client stops capture and the ping timer, rejects a pending `connect()`, and emits a local `socket.closed` event with the close code. Playout events travel the other way. The playout module emits `playout.started`, `playout.stopped` and `cancel.ack`, and your app sends them upstream with `client.send`. The demo widget does this in one line: `startPlayout((e) => { onEvent(e); c?.send(e); })`.

## How playout renders agent audio in order

`Playout` in `src/playout/playout.ts` uses a pull model. An adapter calls `render(out)` once per audio block, and the class fills the block from a queue of agent frames in arrival order, converting PCM16 back to floats. The class has no imports, so `worklet-adapter.ts` injects its source text into an AudioWorklet and runs it on the audio thread.

`startPlayout` creates an `AudioContext` at 24 kHz with the interactive latency hint and a `vc-playout` worklet node. Event times from the audio thread are converted to the page clock, `performance.now()` in microseconds, with `getOutputTimestamp`. That lets the orchestrator compare playout events with mic capture times.

The handle offers `push`, `cancel`, `pause`, `resume` and `close`. Pausing renders silence without counting underruns, and resuming continues from the next sample. The offline adapter `renderMs` renders a given number of milliseconds without a sound card, for tests and the headless client.

## How the playout generation fence works

The playout keeps a fence: the highest cancelled generation. `push` ignores any frame whose generation is at or below the fence. `cancel(gen)` raises the fence to at least `gen` and removes every queued frame at or below it, so frames of a cancelled generation that arrive later are dropped too.

`cancel` always answers with `cancel.ack{gen, played_until_seq}`, which tells the orchestrator how far the user heard:

- if that generation was playing, the value is the sequence of its last frame with at least one rendered sample, and `playout.stopped{reason: "cancel"}` is emitted first;
- if the generation had already played to its end, the value is its last frame;
- if nothing of it was rendered, the value is −1 and no stopped event is sent.

A newer generation plays normally after a cancel: after `cancel(1)`, generation 2 renders. Tests in `playout.test.ts` cover each of these cases.

## How playout reports started, stopped and underruns

`playout.started{gen, t_us}` is emitted at the first rendered sample of a generation, timed at that sample's position in the block rather than the block start. `playout.stopped{gen, reason: "done", t_us}` is emitted when the frame flagged end-of-stream has been rendered, or when a new generation takes over.

Underruns are counted by time, not by sequence. If a generation is playing and the queue runs dry before the block is full, the rest of the block is rendered as silence and its duration is added to `underrunMs`. No frame for 100 ms during a generation adds 100 ms. Silence between generations is not an underrun.

Time-based accounting fits the WebSocket path. TCP delivers frames in order, so a late frame shows up as a gap in time, never as a reordered sequence. The headless client logs the total as `underrun_ms` at the end of a run. The orchestrator uses `playout.started` to line up its echo reference with what the user hears.

## The headless Node client used by benchmarks

`bin/headless-client.ts` runs the real `VoiceClient` and `Playout` in Node, with a WAV fixture as the microphone:

```bash
node packages/web-sdk/bin/headless-client.ts --fixture clip.wav --out log.jsonl [--gateway http://127.0.0.1:8080] [--tail 15] [--text "..."]
```

It fetches a token from `POST /v1/session`, connects to `/v1/ws`, and sends the fixture followed by `--tail` seconds of silence, 15 by default, paced in real time at one frame per 20 ms. Playout renders 20 ms at a time by the wall clock and catches up when a timer fires late. A plain 20 ms interval runs slow in Node, and playback that drifts behind real time misaligns the orchestrator's echo reference. Every event is written as a JSON line stamped with `performance.now()` in microseconds.

For barge-in runs, `--interrupt-after MS` starts the fixture MS after playback begins, `--echo-db` mixes the rendered audio back into the mic 40 ms later, and `--exit-after-cancel-ms` ends the run after a cancel. `harness/runner/wss.py` starts one client per session, 40 in parallel in the largest load test.
