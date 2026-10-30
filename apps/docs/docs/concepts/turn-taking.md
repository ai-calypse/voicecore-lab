---
title: Turn-taking
description: How Silero VAD and the floor state machine decide when the user starts and stops speaking, which audio reaches speech to text, and what the floor reports to the session.
---

## What turn-taking decides

Turn-taking answers one question: who holds the floor, the user or the agent. In this repository one module inside the orchestrator answers it, `voicecore/turntaking/floor.py`. Voice activity detection, endpointing, the echo gate and barge-in share the same session state, so ADR 0001 keeps them together instead of in a separate service. The module works one 20 ms frame at a time. For each mic frame, Silero VAD gives a speech probability, and the floor turns that into decisions: the user started speaking, the user interrupted the agent, or the user finished. Time inside the floor is the sample position. Frame k covers 20k to 20k + 20 ms, and its decisions are stamped at 20(k + 1) ms, the moment the frame has been heard.

## How Silero VAD scores each frame

The VAD is Silero VAD v6.2.3, an ONNX model run locally on onnxruntime with the CPU provider and one thread. The model takes 512 new samples (32 ms at 16 kHz) plus 64 samples of context from the previous window, and it carries a recurrent state of shape [2, 1, 128] from window to window. Mic frames arrive as 20 ms (320 samples), so the wrapper buffers them into 512-sample windows. Each frame reports the probability of the newest complete window, and 0.0 before the first window is complete. The process loads the model once, at server start, because loading it inside the first session stalled that session's mic frames. Every session gets its own state, so conversations do not leak into each other.

## Why the end of speech is reported late

The VAD reports the end of speech about three 20 ms frames late, so every endpoint arrives about 60 ms after the policy's silence would suggest. The offline sweep shows this directly. With real Silero VAD on labelled fixtures, fixed 300 ms of silence gave a median endpoint delay of 340 ms, and fixed 800 ms gave 860 ms (offline fixtures, n = 12). The same offset appears with live providers: the fixed 800 ms policy detected the turn end p50 861 ms after the labelled speech end (live, n = 15). The floor counts silence only from the first frame the VAD scores below the threshold, so this lag adds to every policy. When you set a silence value, expect the measured delay to be that value plus about 60 ms.

## The floor state machine

The floor has two states: nobody holds the floor, or the user holds it. One probability threshold, 0.5, decides whether a frame is voiced. Speech start needs 60 ms (three frames) of consecutive voiced frames. The utterance's start is then set back to its first voiced frame, not to the moment of the decision. While the user holds the floor, a voiced frame resets the silence count, and an unvoiced frame starts it. The turn ends when the active policy's silence has passed, when a punctuated final arrives during the pause (the asr_assisted and eager policies), or 15 s after the utterance started, even if the user is still talking.

| State | Condition | Result |
|---|---|---|
| Nobody holds the floor | 60 ms of consecutive frames with probability ≥ 0.5 | User holds the floor; `speech_started` |
| Nobody holds the floor, echo gate on | 160 ms of frames ≥ 0.7 that also pass the echo power check | User holds the floor; `barge_in` |
| User holds the floor | A voiced frame | Silence count resets; any stored final is cleared |
| User holds the floor | Silence reaches the policy's value | `endpoint`, reason `silence` |
| User holds the floor | Punctuated final and enough silence | `endpoint`, reason `asr` |
| User holds the floor | 15,000 ms since the utterance started | `endpoint`, reason `max_length` |

## How the floor avoids flapping between states

The floor gets its hysteresis from time, not from two thresholds. The same 0.5 threshold applies when speech starts and when it ends, but the two transitions need very different evidence. Entering needs 60 ms of consecutive voiced frames, so a click or a single loud frame does not start a turn. Leaving needs the whole trailing silence, 800 ms with the default fixed policy, with no voiced frame in it. A single voiced frame during a pause restarts the count. The asymmetry is deliberate. A false start costs little, but cutting the user off mid-question costs a whole turn. On the labelled fixtures, every policy gave 0 of 1 false starts on the silence clip (offline fixtures, n = 1).

## How speech is gated to speech to text

The session sends speech to STT and holds back silence, because STT is billed per second and live sessions are capped at 300 s of STT audio. The gate opens when the user holds the floor, or when a frame's probability is at least 0.5 while the agent is not playing and its 200 ms echo tail has passed. It stays open while the user holds the floor and for 30 more frames (600 ms) after the last frame that kept it open, so Finalize sees the whole turn. While the gate is closed, the last 15 frames (300 ms) wait in a pre-roll buffer. When the gate opens, the pre-roll goes first, so the first syllable reaches STT even though speech start is decided 60 ms after it. The STT queue holds 50 frames (1 s). If STT runs slower than real time, the oldest frame is dropped and counted, and the floor never blocks. The mock benchmark had 0 STT queue drops (mock, n = 216).

## Why agent echo does not open the speech gate

While the agent is playing, and for 200 ms after, voiced frames are mostly the agent's own voice coming back through the microphone. If they reached STT, the echo would become words in the user's next transcript, which was seen in live runs. So during playout the STT gate opens only once the user holds the floor through a barge-in. The pre-roll still carries the first syllable. The floor's echo gate decides that barge-in. A frame counts as user speech only if its probability is at least 0.7 (the threshold plus 0.2), and the mic's 100 ms power is no more than 6 dB below the power the client played over the same window plus 40 ms. Speech must also last 160 ms instead of 60 ms. See [Barge-in and echo](./barge-in-and-echo.md).

## What the floor reports to the session

The floor returns events, and the session turns them into turns, generations and protocol events. Every event has a kind and a time `t_ms`. `onset_ms` is the first voiced frame of the utterance. An endpoint also carries its reason (`silence`, `asr` or `max_length`) and `silence_ms`, the trailing silence it waited. In the other direction, the session passes every final transcript to the floor with `transcript_final`, so a punctuated final can end the turn.

| Floor event | What the session does |
|---|---|
| `speech_started` | Starts a new turn ID, resets the transcript, checks for a continuation merge, cancels any active generation and sends `user.speech_started` |
| `barge_in` | The same as `speech_started`; this is how the user interrupts the agent |
| `endpoint` | Moves to thinking, sends Finalize unless it was already sent in this pause, waits up to 5 s for the transcript, sends `transcript.final` and starts a generation |

## How turn-taking is tested

The floor is tested on labelled fixture audio with the real Silero VAD. The labels are exact by construction: the fixture builder trims each LibriSpeech utterance at its first and last loud 20 ms window and pads it with silence it adds itself. For frame-exact unit tests, a fixture VAD returns 1.0 for every frame that overlaps labelled speech and 0.0 otherwise, so a test can check the floor's arithmetic without model noise. `harness/turn_sweep.py` feeds the same frames to every policy and scores endpoint delay, early cut-offs, missed turns, false starts and false barge-ins. The dev split has 12 turns, and the holdout split has 10 turns, run once with the chosen default. These samples rank policies; they are not production rates. See [Endpointing](./endpointing.md) for the results.
