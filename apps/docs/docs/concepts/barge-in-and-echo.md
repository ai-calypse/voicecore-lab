---
title: Barge-in and echo
description: How the agent stops talking the moment you interrupt it, and how it avoids interrupting itself when its own voice comes back through the microphone.
---

## What barge-in means in a voice agent

Barge-in is the user speaking while the agent is still talking. A good voice agent stops its audio at once and starts listening, the way a person does when someone cuts in. Two things can go wrong:

- **A slow or missed barge-in.** The agent keeps talking over you.
- **A false barge-in.** The agent stops itself although nobody spoke, usually because it heard its own voice.

In VoiceCore the turn-taking floor (`voicecore/turntaking/floor.py`) reads every 20 ms mic frame. While the agent is playing, it applies an echo gate before it accepts a frame as speech. When the gated speech lasts long enough, the floor emits a `barge_in` event. The orchestrator session then cancels the playing generation and sends `user.speech_started` to the client.

The cancel travels through every queue as a generation fence, so audio that is already buffered never plays. That mechanism is described in [Generations and cancellation](../concepts/generations-and-cancellation.md). How the floor decides speech start and end outside playback is in [Turn-taking](../concepts/turn-taking.md).

## Why the agent hears its own voice

When the agent plays through laptop speakers, its voice reaches the microphone a few tens of milliseconds later. The voice activity detector (Silero VAD) only answers "is this speech?". It cannot tell the agent's voice from yours, so echo looks exactly like a user starting to talk.

VoiceCore measured this on its echo fixtures, which mix an agent clip back into the mic at −15 dB with a 40 ms delay. With the echo gate turned off, Silero marked the echo as speech on 2 of 2 dev echo-only clips (offline, real Silero VAD on fixture audio). Without a gate, every answer would cancel itself within its first words.

Two layers deal with this. The browser's own echo cancellation removes most of the echo before the audio leaves the page. The orchestrator's echo gate then compares what the mic hears with what the client played, and rejects frames that are probably just echo.

## How the echo gate decides a frame is user speech

The echo gate is on while the agent's audio is playing and for a short tail after it stops. While it is on, and nobody holds the floor yet, a 20 ms mic frame counts as voiced only if both of these hold:

1. The VAD probability is at least the normal threshold plus a boost. With the defaults that is 0.5 + 0.2 = 0.7.
2. The mic's average power over the last 100 ms is no more than 6 dB below the power of the audio the client played over the last 140 ms. The extra 40 ms covers the speaker-to-mic echo delay.

A barge-in then needs 160 ms of such frames in a row, instead of the 60 ms that starts a turn when the agent is silent. The values are fields of `Policy` in `floor.py` and are recorded in ADR 0002.

| Policy field | Default | Meaning |
|---|---:|---|
| `playout_threshold_boost` | 0.2 | added to the VAD threshold during playback |
| `playout_min_speech_ms` | 160 | gated speech needed for a barge-in |
| `echo_gate_db` | −6.0 | mic power must reach played power plus this |
| `echo_tail_ms` | 200 | the gate stays on this long after playback |

## How the orchestrator knows what was playing

The energy comparison needs the power of the agent audio that was coming out of the speaker at the moment each mic frame was captured. The orchestrator rebuilds that from two timestamps on the client's clock, so no clock sync between machines is needed:

- The client sends `playout.started` with `gen` and `t_us` when it renders the first sample of a generation.
- Every mic frame carries `capture_us`, the client time its first sample was captured.

The session keeps every agent frame it sent for the current generation. For each mic frame it takes the offset `capture_us − t_us`, converts it to a position at 24 kHz, and measures the power of the next 480 samples (20 ms). That value feeds the gate's 140 ms played-power window.

This model assumes playback runs in real time from its first sample. If the client's playback stalls and falls behind, the reference no longer matches the echo. A `ponytail:` note in `Session._played_power` records this limit. The fix it names is periodic playout-position events from the client, which the protocol does not have yet.

## Why the energy margin is 6 dB below the played audio

The gate accepts a frame only if the mic is at most 6 dB quieter than the audio being played. This assumes the echo that reaches the mic is at least 6 dB quieter than your voice. Your voice then passes the gate, and the echo alone does not.

The margin is a per-device calibration knob (`echo_gate_db`), not a universal constant. It holds back a user who starts softly under a loud agent syllable. In the offline fixtures, `dev_interrupt_02` barged in 440 ms after the labelled onset for that reason, against 180 and 160 ms for the other two dev interrupt clips (offline, real Silero VAD, n = 3).

On a laptop with loud speakers and browser echo cancellation turned off, the echo may be louder than the 6 dB assumption allows. The gate would then either miss interruptions or, with a looser margin, stop for echo. That trade-off is what the open manual acoustic check is meant to measure.

## Why the gate stays on after playback stops

The gate does not switch off the instant the client reports `playout.stopped`. The last word the agent spoke is still travelling from the speaker, reflecting in the room and reaching the mic. If the gate turned off at once, that tail of echo would be judged with the normal threshold and could start a false user turn.

So each frame that arrives while audio is playing pushes the gate's end time 200 ms forward (`echo_tail_ms`). During those 200 ms the stricter rules still apply: the boosted VAD threshold, the 160 ms minimum and the energy comparison against what was played. After the tail, the floor goes back to the normal 0.5 threshold and 60 ms minimum speech.

The same tail decides when audio may reach speech recognition, which keeps the agent's echo out of the next transcript.

## Why echo of the agent is kept away from speech recognition

During playback, the VAD hears the agent's echo as speech. In the first live barge-in run, those frames were sent to Deepgram, and the agent's own words leaked into the user's next transcript. In the echo-only scripts, the echo transcripts even formed a user turn and triggered follow-up answers.

The fix is in `Session._to_stt`. While the agent is playing, or within the 200 ms echo tail, voiced frames open the STT stream only once the user actually holds the floor, that is, after the echo gate has accepted a barge-in. A 300 ms pre-roll buffer then sends the audio just before the barge-in, so the first syllable is not lost.

Outside playback, a voiced frame opens STT directly, and a 600 ms hangover keeps it open after the last voiced frame. The test `test_echo_of_the_agent_is_not_sent_to_stt_while_it_plays` covers the playback rule.

## Interrupt-to-silence measured with live providers

Interrupt-to-silence is the time from the labelled start of the user's speech to the client's `playout.stopped` with reason `cancel`, measured on the headless client's clock. After both fixes from the first live run, VoiceCore measured:

- **8 of 8 interrupts silenced**, p50 303 ms, p95 1,364 ms (live, n = 8, run `barge_live_20261030T014959Z`).
- **0 of 4 false barge-ins** on echo-only scripts (live, n = 4, run `barge_live_20261030T014851Z`).

The setup: the headless SDK client asks a question about uv by text and plays the grounded answer (Deepgram STT, gpt-4.1-nano, Cartesia sonic-3.6). It simulates a room by mixing its own rendered playback into its mic at −15 dB, about 40 ms late. 1.2 s into playback it starts a recorded user clip. The gateway and orchestrator run on the same laptop, and the providers are reached over the internet.

The p95 comes from one clip whose first word is very short. Measured from the first frame Silero hears as voice, 6 of the 8 interrupts were silenced in about 140–310 ms.

## Interrupt-to-silence measured with fake providers

The in-process benchmark (`harness/barge_bench.py`) runs the real Silero VAD, floor and echo gate on fake time with fake providers. The agent audio is the clip's playout reference, and the client adds a one-way network delay in both directions. Each row is 5 interrupt clips (mock, fake time).

| One-way delay | Silenced | p50 / max | Interrupt-to-listening p50 |
|---:|---:|---:|---:|
| 0 ms | 5 / 5 | 180 / 440 ms | 180 ms |
| 20 ms | 5 / 5 | 220 / 440 ms | 220 ms |
| 50 ms | 5 / 5 | 280 / 480 ms | 280 ms |
| 100 ms | 5 / 5 | 380 / 560 ms | 380 ms |

Each 20 ms of one-way delay adds about 40 ms, because the mic frame travels up and the cancel travels back down. At 0 ms delay the p50 of 180 ms is close to the 160 ms of gated speech the floor waits for. The 4 echo-only clips at 50 ms gave 0 false barge-ins (mock, n = 4). Interrupt-to-listening is the time until the client receives `user.speech_started`.

## Why a short first word can delay barge-in

During playback a barge-in needs 160 ms of gated speech in a row. A very short first word followed by a pause does not reach it, so the barge-in waits for the next word.

The live clip `dev_single_04` shows this. Its speaker says a short first word ("So…") and pauses. Interrupt-to-silence was 1,364 ms, of which about 1,284 ms came after the first voiced frame (live, n = 1). For comparison, `dev_noisy_10db_02` was silenced in 182 ms (live, n = 1).

Some live times also include a lag inside the recording. `dev_single_01` measured 702 ms, but its first voiced frame comes 520 ms after the label, so the system took about 182 ms.

Lowering the 160 ms minimum would catch short first words sooner, but it would also let more echo through as false barge-ins. VoiceCore keeps 160 ms and leaves the choice to the manual acoustic check with real speakers.

## How a drifting test client caused false barge-ins

In the first live barge-in run, all 4 echo-only scripts were cancelled (live, n = 4). Nobody spoke. The agent stopped itself about 8 s into each answer. The 20 in-process fake interrupt runs and the 2 echo fixtures had all passed.

The cause was the headless test client. It rendered playback with a 20 ms `setInterval`, and Node timers fire late. Over 8 s, its real playback fell hundreds of milliseconds behind the orchestrator's model of what was playing. The echo then no longer lined up with the reference: during a pause in the reference, the mic still carried the echo of an earlier word, and the gate saw speech.

The fix: the client renders by the wall clock and catches up, the way a sound card does. Live false barge-ins went from 4 of 4 to 0 of 4, and interrupts were still 8 of 8 silenced, p50 303 ms (live, n = 8).

## Why the fake tests missed the drift bug

The in-process fake client renders agent audio on exact fake time, 20 ms per frame with no jitter. Its playback can never drift from the orchestrator's model, so no fake test could produce the misaligned echo that caused the live false barge-ins. A fake that is too perfect hides timing bugs.

The test that mattered was the live run with a simulated room: real providers, a real network and a client that mixes its own playback into its mic at −15 dB.

The risk is not fully gone. A real browser renders on the audio clock, which does not drift like a Node timer. But a network underrun delays its playback in exactly the same way: the speaker goes quiet while the orchestrator's model keeps running. The `ponytail:` note in `Session._played_power` records this. The upgrade it names is periodic playout-position events from the client, so the orchestrator can correct its reference.

## What browser echo cancellation adds

The browser SDK opens the microphone with `echoCancellation`, `noiseSuppression` and `autoGainControl` all set to true (`packages/web-sdk/src/capture/index.ts`). Browser acoustic echo cancellation (AEC) subtracts the page's own audio output from the mic signal before the frames are sent. Most of the agent's echo should therefore never reach the gateway.

The orchestrator's echo gate is the second line of defence. It handles whatever echo AEC leaves behind, and it protects clients that have no AEC at all.

The measured numbers on this page do not include browser AEC. The live barge-in runs used the headless SDK client, which simulates the room by mixing its playback into its mic, with no AEC. How much browser AEC helps on real laptop speakers, and whether the gate still needs its 6 dB margin with it, is not measured yet.

## Manual acoustic checks that are still open

One check needs a person, real speakers and a real microphone, so it has not been run. The procedure is in `benchmarks/turntaking/echo.md`:

1. Open the demo with `?lab=1`. Set laptop speakers to 70 % volume and use no headphones.
2. With Chrome `echoCancellation: true`, the SDK default, ask 10 questions and stay silent while the agent answers. Count spurious barge-ins.
3. Interrupt 10 answers mid-sentence. Count misses and note the barge-in time from the lab panel.
4. Repeat steps 2 and 3 with `echoCancellation: false`.
5. Record the four counts, the device, the browser version and the room.

Until this runs, the gate's 6 dB margin and 160 ms minimum are tuned on fixtures and simulated rooms only. The browser widget's barge-in timing has not been measured live either.
