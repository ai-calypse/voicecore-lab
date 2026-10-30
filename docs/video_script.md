# Demo video script (about 3 minutes)

Every shot is the real system; numbers on screen come from the linked reports. Record with mock providers unless a live budget is set aside; say which in the first shot.

| Time | Shot (real screen) | Voice-over |
|---|---|---|
| 0:00 | Landing page `http://localhost:5173`, then `docker compose up` in a terminal | "VoiceCore is a voice assistant for the uv docs. I built everything between the mic and the speaker; speech recognition, the language model and the voice are bought. This recording uses mock providers." |
| 0:15 | Click **Ask the uv docs**, tap the mic, ask "How do I install uv?" | "Audio is captured in an AudioWorklet, resampled to 16 kHz and sent as 20 ms frames to a Go gateway." |
| 0:35 | Answer appears with `[1]` links; click one to open the uv docs section | "Every sentence must cite a retrieved passage before it is spoken. Model-written links are stripped." |
| 0:55 | Ask a long question, then interrupt mid-answer | "When I talk over it, the floor detects a barge-in and cancels the generation. Every queue drops that generation's audio, so it goes quiet. Live, that took a median 303 ms." (`reports/barge_in.md`) |
| 1:20 | Block the microphone in the browser, reload, type a question | "If the mic is blocked, the widget says so and text still works." |
| 1:35 | `/?lab=1` timeline: user and agent lanes, the five stage bars, the hatched interrupted generation | "Each process writes the same trace format, aligned to one clock. Here is where a turn's time goes." |
| 2:00 | `reports/latency_chart_light.png` | "Live, a turn went from 2.3 s to 0.84 s at the median, under the hosted Deepgram agent's 0.97 s. The biggest win was endpointing: end the turn eagerly, and if the user keeps talking, cancel the unplayed answer and answer the whole question once." (`reports/latency_tuning.md`) |
| 2:25 | GitHub Actions: `evals` green on main, red on `ci-gate-proof` | "A CI gate replays fixed scenarios on fake time. A branch that adds 200 ms of latency fails it." |
| 2:45 | `docs/writeups/` list | "The write-ups cover what broke: the agent interrupting itself, prompt injection, and the endpointing trade-off." |
