# Write-up 3: 860 ms of silence, on purpose (latency trade-off)

**The problem.** The biggest single slice of voice latency is not a model: it is deciding the user has finished. Live, it is 861 of 2,317 ms (median, n = 15).

**Options measured** (ADR 0002, real Silero VAD on labelled fixtures, then live):

| Policy | Decision latency | Turns cut short |
|---|---:|---:|
| fixed 300–700 ms silence | 340–760 ms (dev fixtures) | 6/12 … 1/12 |
| **fixed 800 ms (chosen)** | 862 ms live median | 0/12 dev, 1/10 holdout, **0/15 live** |
| adaptive 400/700/1,000 ms | 1,060 ms | 1/12 |
| ASR-assisted: 300 ms after a punctuated final | 523 ms live median | **3/15 live** |

**What the live run settled.** ASR-assisted endpointing is about 340 ms faster, which is the best latency lever available. But Deepgram punctuates mid-question pauses ("When moving from pip." … "how do I import my requirements"), so 1 in 5 questions became two turns and two answers. For a docs assistant, cutting the user off costs more than a third of a second, so the default stays at 800 ms.

**The fixture bug found on the way.** In the first sweep the echo gate failed on one interrupt clip. The cause: the fixture builder had mixed that user 16 dB below the agent, so the user was quieter than the echo. Agent and user levels are now both normalised to −23 dBFS. That was a test-data bug, not a gate bug, and it would have led to the wrong calibration.

**Next lever if latency matters more.** Require a punctuated final *and* about 500–600 ms of silence. That keeps most of the gain while giving mid-question pauses a chance. It is unmeasured, so it is not claimed.

**Update: the trade-off went away (same day).** The real cost of an early cutoff was not the wait; it was answering half a question. The fix changes what an early cutoff *does*. The turn ends eagerly: Finalize goes to Deepgram after 200 ms of silence, and a punctuated final ends the turn. If the user keeps talking within 2.5 s, before the answer is audible, that answer is cancelled and the joined question is answered once.

Live, 6 of 27 turns hit an early cutoff. All 6 were merged before any audio played. Turn-end detection fell from 861 to 340 ms at the median. With a faster LLM and a pre-opened TTS socket, the whole turn went from 2,317 to 841 ms ([latency_tuning.md](../../reports/latency_tuning.md)).

The remaining risk is a pause longer than about 800 ms. The early answer then starts to play, and the continuation is treated as a barge-in and a new question.

Evidence: [ADR 0002](../adr/0002-turn-policy.md), [reports/perf.md](../../reports/perf.md), [reports/latency_tuning.md](../../reports/latency_tuning.md).
