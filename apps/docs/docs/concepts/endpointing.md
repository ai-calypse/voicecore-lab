---
title: Endpointing
description: How the orchestrator decides that the user has finished speaking, the four endpoint policies it supports, what each one costs in delay and early cut-offs, and how to change the policy.
---

## What endpointing decides and why it matters

Endpointing is the decision that the user has finished their turn, so the agent can start answering. It is a trade-off with two failure modes. Wait too long and the user hears dead air after every question. Decide too early and the agent cuts the user off mid-question and answers half of it. Before tuning, the endpoint was the largest single slice of a live turn: 861 of 2,317 ms (live p50, n = 15). Silence is not the only signal. This orchestrator can also use the punctuation in the STT's final transcript as evidence that a sentence is complete. The policy lives in `voicecore/turntaking/floor.py` as configuration on a `Policy` dataclass, not as separate classes.

## How endpoint delay and early cut-offs are scored

Every endpoint result in this repository is scored against a labelled turn end, with one rule in `harness/timeline.py`. The first endpoint of an utterance decides. If it comes before the labelled end of the turn, it is an early cut-off. If no endpoint comes at all, the turn is missed. Otherwise, the endpoint delay is the distance from the labelled end to the endpoint, and the median and p95 are taken over those delays with nearest-rank percentiles. Early cut-offs are counted, not averaged in, so a policy cannot look fast by cutting people off. A cut-off is the expensive error: it costs a whole turn, while 100 ms of extra waiting does not.

## The four endpoint policies

The floor supports four policies. All of them share the same speech start rule (60 ms of voiced frames), the same 15 s maximum utterance and the same echo gate. They differ only in how they decide that a pause inside an utterance is the end of it. Two of them use the STT. A final transcript that ends in `.`, `?` or `!` is a punctuated final. Any voiced frame clears the stored final, so only a final that arrives during the current pause can end the turn early. Live mode uses eager by default; mock mode and the CI gate use fixed 800 ms.

| Policy | Ends the turn when | Defaults |
|---|---|---|
| `fixed` | trailing silence reaches `silence_ms` | 800 ms |
| `adaptive` | trailing silence reaches a value set by how long the user spoke before the pause | 400, 700 or 1,000 ms |
| `asr_assisted` | a punctuated final has arrived in this pause and silence is at least `asr_silence_ms`; else the adaptive values | 300 ms |
| `eager` | Finalize at 200 ms of silence; a punctuated final with at least `asr_silence_ms` of silence; else `silence_ms` | 200 ms as the live server sets it, else 800 ms |

### Fixed silence endpointing

The fixed policy ends the turn after `silence_ms` of trailing silence, 800 ms by default. The measured delay is that silence plus about 60 ms of VAD lag. ADR 0002 chose 800 ms as the shortest fixed silence with no early cut-off on the dev fixtures: median 860 ms, p95 980 ms, 0 of 12 early cut-offs (offline fixtures, n = 12). The holdout run gave median 820 ms, p95 880 ms and 1 early cut-off (offline fixtures, n = 10). Live, it answered 15 of 15 questions in one piece (live, n = 15). Its weakness is a speaker who pauses longer than the silence. In `holdout_mid_pause_600ms_01`, the first LibriSpeech sentence has its own pause longer than 800 ms, so the endpoint came at 16,040 ms into the clip while the turn ended at 18,120 ms (offline holdout). Fixed 800 ms is still the default with mock providers and in the CI gate.

### Adaptive endpointing

The adaptive policy picks the silence from how long the user has spoken before the pause. Under 1,000 ms of speech it waits 400 ms, from 1,000 to 3,000 ms it waits 700 ms, and above 3,000 ms it waits 1,000 ms. The idea is that a short reply such as "yes" should end quickly, while a long explanation gets more room to pause. On these fixtures it lost on both axes: median 1,060 ms, p95 1,180 ms and 1 of 12 early cut-offs (offline fixtures, n = 12). The LibriSpeech utterances are 4 to 8 s long, so it mostly waited 1,000 ms. Its 400 ms short-utterance branch cut `dev_single_04` at 1,980 ms into the clip (offline fixtures), during a natural pause right after the first word.

### ASR-assisted endpointing

The asr_assisted policy uses the STT's punctuation as a signal. The turn ends when a punctuated final has arrived during the current pause and the silence has lasted at least `asr_silence_ms`, 300 ms by default. Without such a final, it falls back to the adaptive silences. The session does not send Finalize early with this policy, so the final has to arrive from the STT stream on its own. With a simulated STT that emits a punctuated final 300 ms after each labelled segment end, it gave median 360 ms and 3 of 12 early cut-offs (offline fixtures, n = 12). Live, speech end to LLM request was p50 523 ms, against 862 ms for fixed 800 ms (live, n = 15). But Deepgram punctuated pauses inside 3 of 15 questions, and each half got its own answer.

### Eager endpointing

The eager policy is the live default. When the VAD has heard 200 ms of silence (`finalize_ms`), the session sends Deepgram a Finalize message, once per pause. If a final ending in `.`, `?` or `!` arrives during that pause and the silence has lasted at least `asr_silence_ms`, the turn ends with reason `asr`. The live server sets `asr_silence_ms` to 200 ms for this policy. Otherwise the turn ends after `silence_ms`, 800 ms, exactly as the fixed policy would. On replayed live Deepgram finals it decided p50 400 ms after the speech end, with 5 of 37 early cut-offs (live STT, replayed, n = 37). In full-stack runs, turn end detection fell from p50 861 to 340 ms (live, n = 15). Eager accepts some early cut-offs in exchange for speed, and the continuation merge repairs them.

## Measured trade-off between delay and early cut-offs

The policies were compared at three levels, and each level is closer to real use than the one before. The offline sweep runs real Silero VAD on labelled fixture audio and costs nothing. The endpoint study streams clips to Deepgram once, records every final with its arrival time, and replays that log through each candidate policy for free. The live runs push spoken questions through the whole stack and count what actually happened to each turn. The small samples rank the policies; they are not production rates.

### Offline sweep on labelled fixtures

`harness/turn_sweep.py` runs every policy on the same frames: real Silero VAD v6.2.3 on 12 dev turns. These include single utterances, noisy clips at 10 and 5 dB, speech slowed to 0.8× and clips with a 600 ms pause mid-turn. The asr_assisted rows use a simulated STT that emits a punctuated final 300 ms after each labelled segment end, so they are optimistic about what a real STT does. No policy missed a turn. All gave 0 of 1 false starts on the silence clip and 0 of 2 false barge-ins on the echo-only clips with the gate on.

| Policy (offline fixtures, n = 12) | Median delay | p95 delay | Early cut-offs |
|---|---:|---:|---:|
| fixed 300 ms | 340 ms | 480 ms | 6 / 12 |
| fixed 400 ms | 440 ms | 580 ms | 4 / 12 |
| fixed 500 ms | 560 ms | 680 ms | 3 / 12 |
| fixed 600 ms | 660 ms | 780 ms | 2 / 12 |
| fixed 700 ms | 760 ms | 880 ms | 1 / 12 |
| fixed 800 ms | 860 ms | 980 ms | 0 / 12 |
| fixed 900 ms | 960 ms | 1,080 ms | 0 / 12 |
| fixed 1,200 ms | 1,260 ms | 1,380 ms | 0 / 12 |
| adaptive 400, 700, 1,000 ms | 1,060 ms | 1,180 ms | 1 / 12 |
| adaptive 800, 900, 1,000 ms | 1,060 ms | 1,180 ms | 0 / 12 |
| asr_assisted, 300 ms (simulated STT) | 360 ms | 480 ms | 3 / 12 |
| asr_assisted, 700 ms (simulated STT) | 760 ms | 880 ms | 2 / 12 |

### Live endpoint study with replayed Deepgram finals

`harness/endpoint_study.py --record` streamed 37 dev clips, 25 docs questions and 12 LibriSpeech clips, to Deepgram in real time with Silero VAD alongside. It sent Finalize after 200 ms of VAD silence and logged every final with its arrival time. Without `--record`, the script replays that log through each policy at no cost. Requiring 200, 250 or 300 ms of silence with the final gave identical results, because Deepgram's final arrives about 100 ms after Finalize (live STT, n = 37). Raising it to 400 ms saved one cut-off for 60 ms of median delay. Eager at 200 ms was chosen, with the continuation merge handling its cut-offs.

| Policy (live STT finals, replayed, n = 37) | Delay p50 / p95 | Early cut-offs |
|---|---:|---:|
| fixed 300 ms | 360 / 440 ms | 14 |
| fixed 400 ms | 460 / 540 ms | 12 |
| fixed 500 ms | 560 / 640 ms | 6 |
| fixed 600 ms | 660 / 740 ms | 3 |
| fixed 800 ms | 860 / 940 ms | 0 |
| eager 200 ms, else 800 ms | 400 / 540 ms | 5 |
| eager 400 ms, else 800 ms | 460 / 540 ms | 4 |
| eager 200 ms, else 600 ms | 400 / 540 ms | 7 |

### Live full-stack runs

The live runs sent the same 15 dev docs questions, spoken by a Deepgram Aura voice, through the headless SDK client, the Go gateway, the orchestrator and the live providers. The eager policy was also run on 12 hard LibriSpeech clips: noisy, slowed and with 600 ms pauses mid-sentence. The fixed and asr_assisted runs are compared on speech end to LLM request, because the LLM was much slower during the asr_assisted batch. The eager runs report turn end detection. Both measure when the floor ended the turn.

| Policy (live) | Turns | Questions kept whole | Decision p50 |
|---|---:|---|---:|
| fixed 800 ms | 15 | 15 of 15 | 862 ms (speech end → LLM request) |
| asr_assisted | 15 | 12 of 15; 3 split into two answers | 523 ms (speech end → LLM request) |
| eager, docs questions | 15 | all; early cut-offs merged | 340 ms (turn end detected) |
| eager, hard audio | 12 | all; early cut-offs merged | 340 ms (turn end detected) |

Across both eager runs, 6 of 27 turns hit an early cut-off, and all 6 were merged before any audio played (live, n = 27).

## Why early cut-offs happen

An early cut-off happens when a pause inside one turn looks like the end of it. With the STT-based policies, the cause is punctuation. Deepgram finalises and punctuates at a pause inside a question, for example "When moving from pip." followed by "How do I import my requirements…", or "How do I install uv?" followed by "On a Mac or Linux machine?". With fixed silences, the cause is a speaker whose own pause is longer than the silence. The `holdout_mid_pause_600ms_01` clip was cut at 16,040 ms although the turn ended at 18,120 ms (offline holdout). Without repair, a cut-off produces two answers to two halves of one question. That cost is why ADR 0002 first rejected asr_assisted, and why the eager policy only became the default together with the continuation merge.

## How the continuation merge repairs an early cut-off

The continuation merge turns an early cut-off into one extra LLM call instead of a wrong answer. When the user starts speaking again, the session checks the last voice turn. The merge applies when three things hold. That turn's generation is still the active one. None of its audio is audible yet, because the client has not reported `playout.started`. And the new speech starts within 2.5 s (`MERGE_WINDOW_US`) of the moment the session started answering that turn. The session then cancels that generation, puts the earlier text in front of the new transcript, and answers the joined question once, as the next generation. Live, this happened in 6 of 27 turns, and every cancelled generation was acknowledged with `played_until_seq: -1`, meaning nothing had played (live, n = 27). For example, q06 was answered as "When moving from pip how do I import my requirements? But keep my old pinned versions?". Latency is still measured from the end of the whole utterance to the generation that played.

## Why the merge stops once the answer is audible

The merge applies only before the early answer is audible. Once the client has reported `playout.started` for that answer, new speech is treated as a barge-in and a new question, and the first half is not carried over. This is deliberate. A user who says "stop" after hearing the start of an answer should not get the old question glued in front of "stop". The merge also applies only to voice turns. A typed question clears the stored turn, so text input never joins with an earlier spoken turn. The trade-off is that the session cannot tell a slow speaker from a user who is reacting to what they heard. It decides by whether the user could have heard anything.

## Remaining risk with eager endpointing

The open risk is a pause longer than about 800 ms inside one question (live estimate). That is roughly how long the endpoint, the LLM's first token and the first TTS audio take together. If the user pauses that long after a punctuated final, the answer to the first half starts playing. The continuation is then a barge-in, and the second half becomes a new question without the first half. That did not happen in the live runs: in all 6 early cut-offs the user resumed before any audio played (live, n = 27). The second cost is money. Each merged cut-off spends one extra LLM call. The third is the fallback: when no punctuated final arrives, as with q17, eager waits the full 800 ms (live, n = 15).

## How to choose an endpoint policy

Use eager with live providers. It is the default, and it gave the fastest turn end detection measured here, p50 340 ms (live, n = 15), while the merge kept every question whole (live, n = 27). Use fixed 800 ms with mock providers. The mock STT returns its canned final at every pause, so an STT-based policy would end every turn early. Fixed 800 ms is also the choice when an extra LLM call per early cut-off costs too much. It had 0 early cut-offs on the dev fixtures (offline, n = 12) and on the replayed live finals (n = 37), though 1 on the holdout (offline, n = 10). On the replayed finals it decided p50 460 ms later than eager. Adaptive lost on both delay and cut-offs on these fixtures. asr_assisted is superseded by eager. A rule that needs a punctuated final plus 500 to 600 ms of silence is unmeasured, and so are speculative LLM calls on partial transcripts.

## How to change the endpoint policy

Pass `--policy` to the orchestrator. The choices are `fixed`, `adaptive`, `asr_assisted` and `eager`. Without the flag, the server picks eager with `--providers live` and fixed with mock providers. Eager is built as `Policy("eager", asr_silence_ms=200)`, and every other choice uses the `Policy` defaults. The other knobs, such as `silence_ms`, `adaptive_ms` and `finalize_ms`, are fields on `Policy` in `floor.py` and have no command-line flags. The live benchmark runner takes the same `--policy` flag. ADR 0002 requires a new sweep and an ADR update before you change a default. See [Configuration](../reference/configuration.md).

```bash
# orchestrator with live providers and the fixed 800 ms policy
uv run python -m voicecore.server --providers live --policy fixed

# re-measure: offline sweep, then replay the recorded Deepgram finals (no spend)
uv run python harness/turn_sweep.py
uv run python harness/endpoint_study.py
```
