---
title: Trace events reference
sidebar_label: Trace events
description: Every trace span and event that the orchestrator, gateway and headless client emit, with attributes, the include_text privacy rule and how timeline.py merges them into one session timeline.
---

VoiceCore's processes write trace events as JSON lines, one event per line, in the shape defined in section 5 of `packages/protocol/SPEC.md`. This page lists every event each process emits, with its attributes, then explains the text privacy rule and how the harness merges the logs of one session into a single timeline.

## The trace event shape

Every trace event is one JSON object on one line:

```json
{"trace_id": "s-gw-0cebbb199035ae0c", "span": "llm", "event": "first_token", "t_mono_us": 66378569916, "process": "agent-core", "attrs": {}, "generation_id": 1}
```

- `trace_id`: the session id.
- `span`: the stage the event belongs to, such as `turn`, `stt`, `llm`, `tts`, `playout` or `gateway`.
- `event`: what happened.
- `t_mono_us`: the writing process's own monotonic clock, in microseconds. Clocks of different processes are not comparable without an offset.
- `process`: `agent-core` for the orchestrator, `gateway` for the gateway.
- `generation_id`: present only when the event belongs to a generation.
- `attrs`: extra numbers and labels; `{}` when there are none.

The orchestrator writes one file per session, `<trace dir>/<session id>.jsonl`, when started with `--trace-dir`. The gateway writes one file for all sessions when started with `-trace <file>`.

## Orchestrator turn events

The orchestrator (`runtime/session.py`) emits these events in span `turn`, for turn-taking decisions and typed input:

| Event | Attributes | When |
|---|---|---|
| `speech_started` | `onset_ms`, `capture_end_us` | the user took the floor while no agent audio was playing |
| `barge_in` | `onset_ms`, `capture_end_us` | the user took the floor while agent audio was playing, or within 200 ms after it stopped, while the echo gate is on |
| `continuation` | `generation_id`, `text` | the user resumed within 2.5 s of an endpoint, before the answer was audible; the earlier turn's text is carried into this one |
| `endpoint` | `reason`, `onset_ms`, `silence_ms`, `capture_end_us` | the floor decided the turn is over |
| `text_input` | `text` | a valid typed question arrived |
| `text_input_rejected` | `kind`, `chars` | a typed question was empty, not a string or over 500 characters |

`capture_end_us` is on the client's clock: it is the end of the mic frame that triggered the decision, from that frame's `capture_us`. `onset_ms` is the start of the utterance, in milliseconds of audio counted by the floor. `reason` is `silence`, `max_length` or `asr` (a punctuated final). `silence_ms` is the trailing silence the floor waited. Text attributes are dropped unless `include_text` is on.

## Orchestrator STT, LLM and TTS events

The orchestrator emits these events in spans `stt`, `llm` and `tts`. They time the three provider stages and record their failures and retries. All LLM events and most TTS events carry the `generation_id` they belong to. Error `kind` values are the provider error kinds `retryable`, `rate_limited` and `fatal`, unless noted.

| Span | Event | Attributes | When |
|---|---|---|---|
| `stt` | `final` | `text` | a final transcript arrived from the STT |
| `stt` | `turn_text` | `chars`, `waited_ms`, `text` | the transcript for the turn is settled; `waited_ms` is how long the session waited for it after the endpoint |
| `stt` | `error` | `kind` | the STT stream failed |
| `llm` | `request` | `attempt` | an answer attempt starts; `attempt` counts retries from 0 |
| `llm` | `first_token` | none | the first answer token arrived |
| `llm` | `backoff` | `wait_s` | an HTTP 429 before any text; the session waits 1, 2 then 4 s |
| `llm` | `stall` | `after_s` | no token for 8 s; the agent asks the user to repeat |
| `llm` | `error` | `kind` | the call failed; `kind` is a provider error kind or an exception name |
| `tts` | `first_audio` | none | the first agent audio frame of the generation was sent |
| `tts` | `retry` | none | one retry of speech on a fresh TTS stream |
| `tts` | `error` | `kind` | TTS failed for a generation, or for the stream |

The latency columns use three of these: `llm.request` to `llm.first_token` is the LLM first token, `llm.first_token` to `tts.first_audio` is the TTS first audio, and `turn.endpoint` to `stt.turn_text` is the STT settle.

## Orchestrator playout, runtime and clock events

Besides the provider stages, the orchestrator records what the client reported about playback, which generations it cancelled, and its clock offset to the client. The `playout` events copy the client's own report, so their `t_client_us` is on the client clock while `t_mono_us` is the orchestrator's arrival time. Client events with no special handling are traced in span `client` with the event type as the event name:

| Span | Event | Attributes | When |
|---|---|---|---|
| `playout` | `started` | `generation_id`, `t_client_us` | the client reported `playout.started`; `t_client_us` is the client's time |
| `playout` | `stopped` | `generation_id`, `reason`, `t_client_us` | the client reported `playout.stopped`, reason `done` or `cancel` |
| `playout` | `cancel_ack` | `generation_id`, `played_until_seq` | the client flushed a cancelled generation; −1 means nothing of it played |
| `runtime` | `cancel` | `generation_id`, `reason` | the session cancelled a generation |
| `runtime` | `client_resumed` | none | the gateway reported a resumed client |
| `clock` | `client_offset` | `client_to_agent_us`, optional `final` | the minimum of arrival time minus capture end over the mic frames so far |
| `client` | the event type | none | other client events: `mic.revoked`, `client.paused`, `client.resumed_playout`, and any type the session has no handler for |

`clock.client_offset` is written every 250 mic frames (5 s) and once more with `final: true` when the session closes, so even short sessions get an offset.

## Cancel reasons in runtime cancel events

Every `runtime.cancel` trace event has a `reason` attribute that says why the orchestrator cancelled the generation, and a `generation_id` that says which one. A cancel raises the session's fence to that generation, stops its LLM task and tells TTS to drop its audio. The reason values come from `runtime/session.py`:

| Reason | What caused the cancel |
|---|---|
| `speech_started` | the user started speaking while a generation was still active but not audible, for example during an early-cutoff merge |
| `barge_in` | the user interrupted while the agent was speaking |
| `superseded` | a new generation started, for example from a typed question, while another was active |
| `client_resumed` | the client reconnected; whatever was playing is lost, so it is not spoken twice |
| `paused` | the client reported `client.paused` and the generation stayed paused for 30 s |

Each cancel also sends `agent.cancel` to the client, and the gateway fences its queue on the way.

## Gateway trace events

The gateway (`services/realtime-gateway/session`) emits these events when it runs with `-trace <file>`. All of them are in span `gateway` with process `gateway`. They record the session lifecycle, client attach and detach (for resume), and the generation fence on the client-bound queue, which the orchestrator cannot see:

| Event | Attributes | When |
|---|---|---|
| `session_started` | none | a new session was created and its orchestrator connection opened |
| `client_attached` | `resumed` | a client WebSocket joined the session; `resumed` is true for a resume |
| `client_detached` | `ends_session` | the client WebSocket closed; `ends_session` is false when the session waits for a resume |
| `agent_first_frame` | `generation_id` | the first agent frame of a new, unfenced generation arrived from the orchestrator |
| `fence` | `generation_id`, `dropped_queued` | the gateway forwarded `agent.cancel` and dropped that many queued frames |
| `session_ended` | `reason` | the session ended, for example `expired` |

The gateway trace never contains text. Its file holds all sessions, so a reader filters by `trace_id`. Times are on the gateway's own clock; the merged timeline aligns them with the client's ping and pong.

## Headless client log events

The headless SDK client (`packages/web-sdk/bin/headless-client.ts`) writes its own log, one JSON line per event, with `t_us` on the client's clock and `process` set to `headless`. It is not in the trace shape; the harness converts it when it merges a timeline.

- `client.start`, with the `fixture` path, and `client.end`, with `underrun_ms` of playout underrun.
- `mic.start`, with `t0_us`: frame k's `capture_us` is `t0_us` + 20,000 × k, so fixture labels map onto the client clock.
- `user.onset`, with `onset_us`: when an interrupt clip's labelled speech starts, in barge-in scripts.
- Events the client sent, marked `dir: "out"`: `playout.started`, `playout.stopped` and `cancel.ack`.
- Events the client received, marked `dir: "in"`: every server event, including `welcome`, `pong`, transcripts, `agent.text` and `agent.cancel`, plus `socket.closed` when the WebSocket closes.

The client log does contain transcript and answer text. The merged timeline drops it.

## The text privacy rule for traces

Trace events carry **no transcript or answer text** unless a run explicitly sets `include_text`. Two places enforce the rule, with the same field list: `text`, `transcript` and `answer`.

- **At the source.** `Tracer.emit` in `voicecore/trace.py` drops those attributes before the event is written, unless the tracer was created with `include_text=True`. The orchestrator server never sets it, and no command-line flag turns it on. So `stt.final`, `stt.turn_text`, `turn.text_input` and `turn.continuation` reach the file without their `text`.
- **At the merge.** `merge` in `harness/timeline.py` drops the same fields from every process's events unless called with `include_text=True`. That covers the headless client's log, which records transcripts and answers verbatim. `harness/session_timeline.py` calls `merge` without it.

The rule is tested: `harness/tests/test_timeline.py` checks that a merged timeline has no text unless `include_text` is set. Treat the client logs in a run folder as containing text.

## How the harness merges traces into one timeline

`merge(logs, offsets_us, include_text=False)` in `harness/timeline.py` builds one timeline from per-process event lists:

1. For every process, it adds that process's offset to each event's `t_mono_us`, giving `t_us` on the reference clock.
2. It drops text fields unless `include_text` is set.
3. It sorts all events by `t_us`.

`harness/session_timeline.py` uses it per session of a WSS run. It converts the headless client log into trace-shaped events with process `client`, mapping playout events and `cancel.ack` to span `playout`, `mic.start` and `user.onset` to `capture`, `text.input` to `turn`, and everything else to `client`. It skips `pong`, `client.start`, `client.end` and `socket.closed`. It then picks the gateway events with this session's `trace_id`, merges them with the orchestrator trace, and writes `timelines/<session id>.json`.

## The merged timeline file format

Each `timelines/<session id>.json` file written by `harness/session_timeline.py` has these fields:

- `session_id`: the session.
- `reference_clock`: always `client`. Every `t_us` is on the headless client's clock.
- `offsets_us`: the offset added to each process's times, for `client` (always 0), `gateway` and `agent-core`.
- `offset_notes`: how each offset was found. The gateway's is "ntp from ping/pong". The orchestrator's is labelled derived, because it includes the smallest uplink delay.
- `events`: every event with its original fields plus `t_us`, sorted by `t_us`, with `trace_id` set to the session id.

Gateway events are included only when the client log has pongs, and orchestrator events only when the trace has `clock.client_offset` events, because without them there is no offset. `harness/lab_sample.py` adds two optional fields, `label` and `gateway_counters`. The demo's lab view (`?lab=1`) reads this format.

## How clock offsets are computed for the merge

The merged timeline puts every process on the client's clock. The client's offset is 0; the other two are measured.

- **Gateway, NTP style.** Every 2 s the client sends `ping` with its time `t_client_us`; the gateway answers `pong` with `t_client_us` and its own `t_server_us`. The client logs the pong with its receive time. `ntp_offset` takes the sample with the smallest round trip, assumes the gateway read its clock at the midpoint, and returns gateway time minus client time. The timeline subtracts it.
- **Orchestrator, derived.** For every mic frame, the orchestrator computes its arrival time minus the frame's capture end on the client clock, and keeps the minimum as `clock.client_offset`. The timeline subtracts the smallest value.

The orchestrator offset therefore includes the smallest one-way uplink delay, which is why it is labelled derived. Latency columns from `harness/latency.py` never depend on these offsets: each is measured on one clock.
