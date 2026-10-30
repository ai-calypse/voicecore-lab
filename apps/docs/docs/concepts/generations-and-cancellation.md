---
title: Generations and cancellation
description: How every agent answer gets a generation id, and how one fencing rule stops stale tokens and audio in the orchestrator, the gateway and the browser.
---

## What a generation is

A generation is one attempt by the agent to speak: one answer, or one fixed reply such as "Sorry, could you say that again?". Each generation gets a generation id, an unsigned 32-bit number that increases by 1 for every new generation in a session and never repeats.

The id travels with everything the generation produces:

- **Agent audio frames.** The 28-byte frame header has a `generation_id` field. Mic frames always carry 0. The orchestrator also uses the generation id as the frame's `stream_id`, and numbers its frames from sequence 0.
- **Control events.** `agent.generation_started` carries `turn_id` and `gen`. `agent.text`, `answer.sources` and `agent.cancel` carry `gen`.

One user turn can have more than one generation. A typed question that arrives while the agent is still thinking supersedes the first answer. An early endpoint followed by more speech cancels the first answer and starts a merged one.

The orchestrator session (`voicecore/runtime/session.py`) treats a generation as alive only while it is the newest one, is above the fence and the session has not ended. Everything else is stale and gets dropped.

## Why voice agents need generation ids

A streaming voice agent produces audio ahead of playback. By the time you hear the first word of an answer, later words are already buffered at several hops:

- in the TTS provider's socket, still arriving;
- in the orchestrator, on their way to the gateway;
- in the gateway's client-bound queue, which holds up to 1,500 agent frames (30 s);
- in the browser playout queue.

When you interrupt, all of that audio must disappear. A cancel message, though, races with frames that are already in flight. A queue that receives a frame after the cancel cannot tell, from the audio alone, whether the frame belongs to the cancelled answer or to the new one.

The generation id answers that question at every hop without coordination. Each queue only has to remember the highest cancelled id. Any frame at or below it is stale, whenever it arrives. This is what makes barge-in reliable: see [Barge-in and echo](../concepts/barge-in-and-echo.md) for how the interruption itself is detected.

## The fencing rule every queue applies

The wire protocol (`packages/protocol/SPEC.md`, section 3) defines one rule for every queue owner: the orchestrator's outbound path, the gateway's send queue and the browser playout.

```text
on cancel of generation g:
    fence = max(fence, g)
    drop every queued agent frame with generation_id <= fence
on every agent frame:
    if generation_id <= fence: drop it
```

Three properties make the rule safe:

- **It is idempotent.** Applying the same cancel twice changes nothing.
- **Order does not matter.** Because of `max`, a late cancel for an older generation can never lower the fence and revive anything.
- **It covers frames already queued.** Cancelling purges the queue, so buffered audio of a cancelled answer never plays.

The gateway learns `g` from the `agent.cancel` event it forwards to the client. The browser applies the same fence and acknowledges with `cancel.ack`. See the [wire protocol reference](../reference/wire-protocol.md) for the event fields.

## How the orchestrator fences its own output

The session keeps two numbers: `gen`, the newest generation id, and `fence`. A generation `g` is alive only if `g == gen`, `g > fence` and the session has not ended. The session checks this at every step where stale output could escape:

- after each item the answer stream yields, before it is spoken;
- before each piece of text is sent to TTS;
- for each chunk of TTS audio that arrives;
- before each agent frame is sent to the gateway.

`Session.cancel(g)` sets `fence = max(fence, g)`, clears the playing state, cancels the LLM task, tells TTS to cancel `g` and sends `agent.cancel` with `gen` downstream.

The Cartesia TTS adapter keeps its own fence too. Cartesia's cancel only stops requests that have not started generating, so the adapter sends the cancel for that generation's context and also drops any audio that still arrives for it. Frames that the session drops as stale are counted in `dropped_stale`.

## How the gateway fences its send queue

The Go gateway (`services/realtime-gateway/session/session.go`) applies the fence in its upstream reader, between the orchestrator and the client:

- **Agent frames.** Each frame's `generation_id` is compared with the session's fence. A frame at or below the fence is dropped and counted in `drops_fenced`. Others go into the client-bound queue.
- **The agent.cancel event.** When it passes through, the gateway sets `fence = max(fence, g)`, purges every queued frame of generation `g` or older, and writes a `fence` trace event with the number of frames it dropped. It then forwards the event to the client.

Purging matters because the client-bound queue can hold up to 1,500 agent frames, 30 s of audio. Without the purge, a slow client connection would keep playing a cancelled answer from the gateway's buffer.

You can read `drops_fenced` and the other counters at `GET /debug/counters` on the gateway. The gateway is described in [Realtime gateway](../architecture/realtime-gateway.md).

## How the browser playout fences and acknowledges

The browser plays agent audio through the `Playout` class (`packages/web-sdk/src/playout/playout.ts`). It runs inside an AudioWorklet, so it renders on the audio thread.

- **Push.** A frame whose generation is at or below the fence is ignored on arrival.
- **Cancel.** `cancel(gen)` sets `fence = max(fence, gen)` and removes every queued chunk at or below the fence. If the generation being played is fenced, it emits `playout.stopped` with reason `cancel`. Then it always emits `cancel.ack` with `gen` and `played_until_seq`.
- **New generation.** The first rendered sample of a newer generation emits `playout.started` with `gen` and the render time.

The SDK client applies `agent.cancel` to the playout before your application's event handler sees the event. By the time your code reacts to the cancel, the stale audio is already gone. The unit tests in `playout.test.ts` check that no sample of a cancelled generation is rendered, even for a frame pushed after the cancel.

## What the cancel acknowledgement reports

The browser answers every cancel with `cancel.ack`, carrying `gen` and `played_until_seq`. `played_until_seq` is the sequence number of the last frame of that generation that had at least one sample rendered:

- If the cancelled generation was playing, it is the last frame you heard part of.
- If nothing of it was rendered yet, it is −1.
- If the generation had already played to its end, it is that generation's last frame.

Together with the frame size (20 ms at 24 kHz), this tells the server exactly how much of the answer reached your ears. That is the information an agent needs to say "as I was saying" or to know which part of an answer was never heard.

In the current code the orchestrator records `cancel.ack` only in its trace, as a `playout` `cancel_ack` event with `played_until_seq`. No decision depends on it yet. The barge-in benchmark uses the related `playout.stopped` event, with reason `cancel`, to measure interrupt-to-silence.

## The events that cancel a generation

The orchestrator cancels the active generation in four situations. Each cancel is traced with a reason.

| Reason | When it happens |
|---|---|
| `barge_in` or `speech_started` | the floor detects the user speaking while a generation is active, during playback or while the agent is still thinking |
| `superseded` | a new generation starts, for example a typed question arrives during an answer |
| `client_resumed` | the client reconnected within the resume window |
| `paused` | the client reported a pause and did not resume within 30 s |

For a user who starts speaking, the cancel comes first and `user.speech_started` follows. The client stops the old audio before it shows that it is listening.

A cancel only applies to the active generation. A cancel request for any other id is ignored, so cancelling twice, or cancelling something that already finished, does nothing.

## How stale tokens and stale audio are dropped

Cancelling a generation does not stop the providers at once. The LLM may still be streaming tokens, and the TTS provider may still send audio for text it already accepted. Those late results are stale, and the alive check drops them before they reach a queue.

The orchestrator tests cover the cases that matter:

- `test_late_llm_token_for_a_cancelled_generation_never_reaches_the_outbound_queue`
- `test_late_tts_audio_for_a_cancelled_generation_is_dropped`
- `test_any_event_sequence_keeps_one_generation_and_never_sends_an_older_one`

The last one is a property test. It runs random sequences of typed questions, pauses, playout events and resumes on fake time. It then checks that every frame and answer event belonged to the newest generation when it was sent, and that the `agent.cancel` ids only ever increase.

The architecture rule is simple to state: once a generation is fenced, nothing it produces can reach your speaker.

## Why a resumed connection cancels the live generation

If the client's connection drops, the gateway keeps the session and its upstream connection to the orchestrator for 10 s. A `hello` that carries the old `session_id` within that window resumes the session.

On resume, the gateway sets its fence to the newest generation it has seen and purges its client-bound queue. Audio queued while the client was away is dropped. It does this before it sends `welcome`. Once the client has `welcome`, a new generation may already be on its way, and it must not be caught by this fence. That ordering was found through a flaky test.

The gateway then sends `client.resumed` upstream. The orchestrator cancels the active generation with reason `client_resumed`. Whatever was playing when the connection dropped is lost, and the agent does not speak it again from the middle. Clients pick a random first `stream_id`, so a resumed session never sees a reused mic stream number.

## Recovery when speech recognition returns no final

When the floor detects the end of your turn, the orchestrator asks the STT provider to finalize and then waits. It needs a final transcript and no interim result still pending. It waits at most 5 s (`final_wait_s`).

- **A final arrives.** The text becomes the question, and a new generation answers it.
- **Nothing usable arrives within 5 s.** The orchestrator starts a generation that says "Sorry, could you say that again?" instead of answering an empty question.
- **You start speaking again during the wait.** The turn changed, so the wait is abandoned and the new turn takes over.

The test `test_no_stt_final_5s_after_endpoint_reprompts` covers the timeout. This path matters with live STT: a provider can return only silence, or a final can be lost on the network. In both cases you get a short, spoken request to repeat yourself instead of a silent agent. How the end of a turn is detected is covered in [Endpointing](../concepts/endpointing.md).

## Recovery when the LLM stalls or fails

The orchestrator never leaves a turn without an answer and an end. Every answer attempt reads the LLM stream with a stall timeout of 8 s per item (`stall_s`).

- **The stream stalls for 8 s.** The generation speaks "Sorry, could you say that again?" after whatever it already said.
- **A provider error or an unexpected exception.** The generation speaks "Sorry, I'm having trouble answering right now. Please try again."
- **An HTTP 429 before any answer text.** The orchestrator backs off and retries, described in its own section.

In each case the generation still ends normally: the final text goes out as `agent.text`, TTS gets its last chunk, and the session returns to listening when playback is done. While the LLM stalls, mic frames keep reaching STT, so you can still interrupt or ask again. The tests `test_llm_silent_for_8s_reprompts` and `test_an_unexpected_llm_error_mid_stream_still_ends_the_turn_with_an_apology` cover these paths.

## Backoff after an HTTP 429 from the LLM

An HTTP 429 means the LLM provider is rate-limiting you. If it arrives before any answer text, nothing has been said yet, so a retry is safe. The orchestrator waits 1 s, then 2 s, then 4 s between attempts (`BACKOFF_S`).

- If an attempt succeeds, the answer streams normally.
- If all retries are rate-limited, the generation says "I'm busy right now. Please try again in a moment."
- If the generation is cancelled during a wait, for example because you speak, the retries stop.

A 429 that arrives after answer text has started is not retried, because a retry could repeat words you already heard. It is handled like any other provider error, with the "having trouble" apology. The tests `test_http_429_backs_off_1_2_4s_then_says_it_is_busy` and `test_429_then_success_answers_normally` cover both outcomes.

## Recovery when TTS disconnects

A TTS failure must not lose the answer. When the TTS stream fails, the orchestrator still sends the full answer as `agent.text`, so a text client or the widget's transcript shows it.

Then it retries speech once, on a fresh TTS stream, but only if none of this generation's audio has been sent yet. If part of the answer was already played, a retry would repeat speech, so it does not retry. The retry also never reuses a fragment of the failed attempt's audio.

If the failure is fatal, for example because the TTS credit reservation was refused, there is no retry and the session answers in text only. If the retry is not possible or also fails, the generation ends and the session returns to listening, because no audio will ever end it. The tests `test_tts_disconnect_sends_the_text_answer_and_retries_tts_once_on_a_new_stream` and `test_a_late_tts_error_after_the_text_was_sent_is_retried_once` cover this.

## What happens when the client pauses playout

The protocol defines `client.paused` for a hidden page or paused playout, and `client.resumed_playout` for when playout continues. In the browser, `Playout.pause()` stops rendering without counting the time as an underrun, and `resume()` continues from the next sample.

When the orchestrator receives `client.paused` during a generation, it starts a 30 s timer (`PAUSE_CANCEL_S`) for that generation:

- `client.resumed_playout` before 30 s clears the timer, and the answer continues where it stopped.
- After 30 s without a resume, the orchestrator cancels the generation with reason `paused`. A long-forgotten answer does not start talking when you return to the tab.

The timer follows the current generation. If a new generation replaces the paused one, the old timer is cleared. The tests `test_client_paused_over_30s_during_a_generation_cancels_it`, `test_client_resuming_playout_before_30s_keeps_the_generation` and `test_the_pause_timer_follows_the_current_generation` cover these rules.

## What happens when the microphone is revoked

You can stop the microphone, or the browser can lose it, while the session stays open. The SDK's `stopMic()` stops capture and sends `mic.revoked`.

The orchestrator then:

- ignores any further frames from that mic stream id;
- resets the floor, the transcript and the STT window;
- drops a half-spoken turn instead of answering half a question;
- returns from user speaking to listening.

Text input keeps working, so you can still type questions and get spoken or text answers. Starting the microphone again uses a new stream id, and the SDK's `startMic()` asks for consent again. A new stream id means new consent, so its frames are accepted.

The tests `test_mic_revoked_stops_voice_but_text_still_works` and `test_revoking_the_mic_mid_utterance_drops_the_half_turn` cover both cases. For failures you see from the outside, see [Troubleshooting](../guides/troubleshooting.md).
