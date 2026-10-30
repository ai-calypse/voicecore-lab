# ADR 0002: Default turn-taking policy

**Status:** Accepted, 2026-10-30; confirmed with live STT 2026-10-30 (see Live check). **Amended 2026-10-30:** with live providers the default is now `eager` (see the last section); fixed 800 ms stays the default with mock providers and in the CI gate. **Task:** S02-T05. **Owner module:** `services/agent-core/voicecore/turntaking/floor.py`.

## Decision

Default endpointing is **fixed trailing silence of 800 ms** (`Policy()`), with speech start after 60 ms of voiced frames, a 15 s maximum utterance, and the echo gate on while the agent is playing (VAD threshold +0.2, 160 ms minimum speech, mic 100 ms power ≥ played power − 6 dB, 200 ms echo tail). `asr_assisted` stays available but is not the default until it is measured with a live STT (Step 06).

## Evidence

`uv run python harness/turn_sweep.py` (raw: [`reports/turn_policy.json`](../../reports/turn_policy.json), [`reports/turn_policy.txt`](../../reports/turn_policy.txt), plot [`reports/turn_policy.png`](../../reports/turn_policy.png)). Silero VAD v6.2.3 on onnxruntime runs on the real fixture audio; labels are exact by construction (S00-T03). Endpoint delay = first endpoint − labelled turn end; an endpoint before the labelled end is an early cutoff (`harness/timeline.py`). The asr_assisted rows use a **simulated** STT that emits a final with a full stop at each labelled segment end + 300 ms.

Dev split, 12 turns (single, noisy 10/5 dB, slow 0.8×, mid-pause 600 ms):

| Policy | Median delay | p95 delay | Early cutoffs |
|---|---:|---:|---:|
| fixed 300 ms | 340 ms | 480 ms | 6 / 12 |
| fixed 500 ms | 560 ms | 680 ms | 3 / 12 |
| fixed 700 ms | 760 ms | 880 ms | 1 / 12 |
| **fixed 800 ms** | **860 ms** | **980 ms** | **0 / 12** |
| fixed 900 ms | 960 ms | 1,080 ms | 0 / 12 |
| adaptive 400/700/1000 | 1,060 ms | 1,180 ms | 1 / 12 |
| asr_assisted (300 ms after a punctuated final; simulated) | 360 ms | 480 ms | 3 / 12 |

All policies: no missed turns, 0/1 false starts on the silence clip, 0/2 false barge-ins on echo-only clips with the gate on, barge-in 180 / 440 / 160 ms after the labelled user onset on the 3 dev interrupt clips.

**Holdout, run once with the chosen default** ([`reports/turn_policy_holdout.json`](../../reports/turn_policy_holdout.json)), 10 turns: median 820 ms, p95 880 ms, **1 early cutoff**, 0 missed, 0/1 false starts, 0/2 false barge-ins, barge-in 180 / 200 ms.

Endpoint delay is the policy's silence plus about 60 ms: Silero reports the end of speech roughly three 20 ms frames late.

## Why this default

- 800 ms is the shortest fixed silence with no early cutoff on dev. Cutting a user off mid-question costs a whole turn, while 100 ms of extra wait does not.
- `adaptive` (400 / 700 / 1000 ms) lost on both axes here. LibriSpeech utterances are 4–8 s long, so it mostly waits 1,000 ms, and its 400 ms short-utterance branch cut `dev_single_04` at 1,980 ms during a natural pause right after the first word.
- `asr_assisted` is 500 ms faster at the median but cut both mid-pause clips: a final transcript with a full stop arrives during a 600 ms pause between two sentences of one turn. Whether a real STT punctuates at that point is unmeasured. Step 06 repeats the comparison with Deepgram finals.

## Known failure cases

- `holdout_mid_pause_600ms_01`: endpoint at 16,040 ms, but the turn ends at 18,120 ms. The first LibriSpeech sentence has its own pause longer than 800 ms of VAD silence. Any fixed policy short enough to feel responsive cuts a speaker who pauses for that long.
- `dev_interrupt_02`: barge-in 440 ms after onset. The user's first syllables are soft while the agent is loud, so the energy gate holds them back. The gate margin (−6 dB) assumes the echo is at least 6 dB below the user. On a laptop with loud speakers and no browser AEC, that may not hold. It is a per-device calibration knob, and the manual check in [`benchmarks/turntaking/echo.md`](../../benchmarks/turntaking/echo.md) still has to be run.
- 12 dev and 10 holdout turns is a small sample. These numbers rank policies; they are not production rates.

## Consequences

- `Policy()` defaults to `fixed`, `silence_ms=800`; changing it needs a new sweep and an update here.
- During the S00-T03 → S02 work, the fixture builder was found to mix interrupting users at their raw LibriSpeech level: one user was 16 dB below the agent, so quieter than the echo. Agent clips and interrupting users are now both set to −23 dBFS (rebuilt 2026-10-30, `harness/build_fixtures.py`).

## Live check (S06-T04, 2026-10-30)

The same 15 dev docs questions were run through the full stack twice with live Deepgram finals ([`reports/perf.md`](../../reports/perf.md)):

- **fixed 800 ms:** 15 / 15 answered in one piece; speech end → LLM request p50 862 ms.
- **asr_assisted:** p50 523 ms (about 340 ms sooner), but 3 / 15 questions were cut at an internal pause, because Deepgram punctuated mid-question.

The default stays fixed 800 ms. A gate that needs both punctuation and a longer silence (for example 600 ms) is the next thing to try if latency matters more than the occasional split.

## Amendment: eager endpoint for live providers (2026-10-30)

**Decision:** with live providers the orchestrator uses `Policy("eager", asr_silence_ms=200)`:

- send Deepgram `Finalize` once VAD has heard 200 ms of silence;
- end the turn when a final ending in `.`, `?` or `!` arrives with at least 200 ms of silence;
- otherwise end it after 800 ms, as before.

**Continuation merge:** when the user speaks again within 2.5 s of an endpoint and before the answer is audible, the session cancels that answer and answers the joined text once.

**Evidence** ([`reports/latency_tuning.md`](../../reports/latency_tuning.md)):

- **Replayed live Deepgram finals, 37 dev clips:** decision p50 400 ms against 860 ms for fixed 800, with 5 / 37 early cutoffs.
- **Full stack:** 6 of 27 live turns hit an early cutoff. All 6 were merged before any audio played, and each was answered from the complete question.
- **Speed:** turn end detected p50 340 ms against 861 ms.

**Why the earlier objection no longer holds:** `asr_assisted` lost because an early cutoff produced two answers to two halves. With the merge, an early cutoff costs one extra LLM call instead.

**Remaining risk:** if the user's pause is longer than about 800 ms (endpoint + LLM + TTS), the half-question answer starts playing. The continuation is then a barge-in and a new question, without the first half.

**Mock mode keeps fixed 800 ms.** The mock STT returns its canned final at every pause, which would end every turn early.
