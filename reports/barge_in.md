# Barge-in and recovery (S05-T04)

**Date:** 2026-10-30 UTC. **Definitions** (`harness/barge_bench.py`, `harness/barge_live.py`):
- **Interrupt-to-silence** is the time from the labelled start of the user's speech to the client's `playout.stopped{reason: cancel}`, measured on one clock: fake time in-process, or the headless client's clock live.
- **Interrupt-to-listening** is the time from that same onset to the client receiving `user.speech_started`.
- **False barge-in** is any cancel during a script in which nobody interrupts.

**Kill gate (master plan):** cancelling mid-TTS silences the client. **Passed:** 20/20 fake, 15/15 and 8/8 live.

## Fake providers, in-process, fake time (`fake-provider`, n = 24)

- **Runtime:** real Silero VAD, floor and echo gate.
- **Agent audio:** the clip's `playout_ref` audio, starting at 500 ms, where the fixture's echo begins.
- **Network:** the client adds a one-way delay in both directions.

`uv run python harness/barge_bench.py` → [`barge_in_fake.json`](barge_in_fake.json).

| One-way delay | Interrupts silenced | Interrupt-to-silence p50 / max | Interrupt-to-listening p50 |
|---:|---:|---:|---:|
| 0 ms | 5 / 5 | 180 / 440 ms | 180 ms |
| 20 ms | 5 / 5 | 220 / 440 ms | 220 ms |
| 50 ms | 5 / 5 | 280 / 480 ms | 280 ms |
| 100 ms | 5 / 5 | 380 / 560 ms | 380 ms |

Echo-only clips at 50 ms: **0 / 4** false barge-ins. Each 20 ms of one-way delay adds about 40 ms: the mic frame travels up and the cancel travels down. The 440 ms case is `dev_interrupt_02`, whose user starts softly under a loud agent syllable (ADR 0002).

## Live providers (`live-provider`)

- **Script:** the headless SDK client asks "How do I start a new project with uv and add a dependency to it?" by text and plays the grounded answer (Deepgram STT, gpt-4.1-nano, Cartesia sonic-3.6).
- **Simulated room:** the client mixes its own rendered playback into its mic at −15 dB, about 40 ms late.
- **Interruption:** 1.2 s into playback the client starts a dev user clip.
- **Setup:** gateway and orchestrator on the same laptop, providers over the internet.

| Run | Scripts | Silenced | Interrupt-to-silence p50 / p95 | False barge-ins (echo only) |
|---|---:|---:|---:|---:|
| `barge_live_20261030T014442Z` + `…014507Z` (client before the render fix) | 16 interrupts + 4 echo-only | 16 / 16 | 284 / 1,404 ms | **4 / 4** |
| `barge_live_20261030T014851Z` (after both fixes) | 4 echo-only | — | — | **0 / 4** |
| **`barge_live_20261030T014959Z` (after both fixes)** | 8 interrupts | **8 / 8** | **303 / 1,364 ms** | — |

Per user clip (fixed run), interrupt-to-silence and the clip's label-to-voice lag. The lag is the time from the label to the first Silero frame ≥ 0.5 in the clean clip:

| User clip | Interrupt-to-silence | Label-to-voice lag | From the voice |
|---|---:|---:|---:|
| dev_single_01 | 702 ms | 520 ms | ~182 ms |
| dev_single_02 | 303 ms | 100 ms | ~203 ms |
| dev_single_03 | 346 ms | 40 ms | ~306 ms |
| dev_single_04 | 1,364 ms | 80 ms | ~1,284 ms (short first word, then a pause) |
| dev_noisy_10db_01 | 201 ms | 20 ms | ~181 ms |
| dev_noisy_10db_02 | 182 ms | 40 ms | ~142 ms |
| dev_slow_0_8x_01 | 264 ms | 40 ms | ~224 ms |
| dev_slow_0_8x_02 | 622 ms | 100 ms | ~522 ms |

## What the live run found (and fixed)

1. **False barge-ins near the end of long answers (4/4).**
   - **Cause:** the headless client rendered playback on a 20 ms `setInterval`, which runs slow in Node. After about 8 s, its real playback lagged the server's model of "what is playing now" by hundreds of ms, so the echo gate compared the mic with the wrong stretch of agent audio.
   - **Fix:** the client renders by the wall clock, as a sound card does. Result: 0/4.
   - **Why the fakes missed it:** the in-process fake client renders on exact fake time.
   - **Remaining risk:** a real browser renders on the audio clock, but an underrun shifts its playback the same way. That is recorded as a `ponytail:` note in `Session._played_power`; the fix would be periodic playout-position events.
2. **The agent's own echo was transcribed.** During playback the VAD hears the echo, and STT received it. Its words then leaked into the next user turn.
   - **Fix:** STT opens during playback only once the user holds the floor. The 300 ms pre-roll keeps the first syllable.
   - **Test:** `test_echo_of_the_agent_is_not_sent_to_stt_while_it_plays`.
3. **Known weakness, not fixed:** a very short first word ("So…") followed by a pause does not reach the 160 ms of gated speech needed during playback, so barge-in waits for the next word (`dev_single_04`, 1.3 s). Lowering the minimum trades this against false barge-ins on echo, so it is left for the manual acoustic check.

## Not run: manual acoustic loopback (label `manual`)

Five runs with real laptop speakers and microphone, browser AEC on, using the demo page from Step 08. This needs a person, so it is open; the procedure is in [`benchmarks/turntaking/echo.md`](../benchmarks/turntaking/echo.md).

## Spend

Step 05 live runs: $0.019 and about 4,950 Cartesia credits, over the planned 3,000. The first echo-only run also triggered follow-up answers, because echo transcripts formed a user turn. Pools after Step 05: usd **$0.738** of $5.00, Cartesia **6,446** of 16,000.
