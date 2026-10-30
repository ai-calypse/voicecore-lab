# Write-up 1: the agent interrupted itself (bug, found live)

**What happened.** In the first live barge-in run (S05-T04), 4 of 4 "echo only" scripts were cancelled. Nobody spoke; the agent stopped itself about 8 s into each answer. The 20 in-process fake runs and the 2 echo fixtures had passed.

**How the echo gate works.** While the agent plays, a mic frame counts as user speech only if the VAD is surer than usual and the mic is no more than 6 dB below the audio the client played over the same 100 ms (plus a 140 ms echo window). The orchestrator reconstructs "what was playing at mic time T" from the client's `playout.started` timestamp, assuming playback runs in real time.

**Root cause.** The headless test client rendered playback with a 20 ms `setInterval`, and Node timers fire late. Over 8 s its real playback fell hundreds of milliseconds behind the orchestrator's model. The echo then no longer lined up with the reference: during a pause in the reference, the mic still carried echo of an earlier word, so the gate saw "speech". The fake client renders on exact fake time, so no fake test could see this.

**Fix.** The client renders by the wall clock, catching up like a sound card. Live false barge-ins went from 4/4 to 0/4, and interrupts were still 8/8 silenced, median 303 ms.

**The same run found a second bug.** The agent's echo was being sent to STT, and its words leaked into the user's next turn. STT now opens during playback only when the user holds the floor.

**What is still true.** A real browser renders on the audio clock, but a network underrun shifts its playback in exactly the same way. A `ponytail:` note in `Session._played_power` records it, and the fix is periodic playback-position events from the client. Lesson: a fake that is *too* perfect hides timing bugs. The live run with a simulated room (the client mixes its own playback into its mic at −15 dB) was the test that mattered.

Evidence: [reports/barge_in.md](../../reports/barge_in.md), `benchmarks/raw/barge_live_*`.
