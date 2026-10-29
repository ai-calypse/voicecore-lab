# Glossary

Domain words used in code, tests and docs. Use these names; add a term here before naming a module after a new concept.

| Term | Meaning |
|---|---|
| **Session** | One browser connection to the system, from `hello` to `session.ended`. Survives a reconnect inside the resume window. |
| **Stream** | One ordered sequence of audio frames in one direction (mic up, agent down), identified by `stream_id`. |
| **Frame** | One binary protocol message: 28-byte header + PCM16 payload. Mic frames are 20 ms at 16 kHz (320 samples). |
| **Turn** | One user contribution and the agent's reply to it. |
| **Utterance** | A stretch of user speech, possibly with short pauses inside it. |
| **Endpoint** | The moment the turn-taking module decides the user has finished an utterance. |
| **Floor** | Who is allowed to speak now. The turn-taking module owns the floor and emits `speech_started`, `endpoint` and `barge_in`. |
| **Generation** | One agent response (LLM text + TTS audio), numbered by a per-session increasing `generation_id`. |
| **Fence** | The highest cancelled `generation_id`. Every queue owner drops frames with `generation_id <= fence`. |
| **Stale** | A result or frame that belongs to a generation at or below the fence. Stale data must never be played. |
| **Barge-in** | The user starts speaking while the agent is speaking; the current generation is cancelled. |
| **Playout** | Turning agent frames into sound in the browser, in order, with `playout.started` / `playout.stopped` events. |
| **Underrun** | Playout had no frame when it needed one and rendered silence; measured in ms. |
| **Interrupt-to-silence** | Time from the user's speech onset during agent speech to the client's `playout.stopped`. |
| **Trace span** | A named stage in a turn (e.g. `stt.final`, `llm.first_token`, `tts.first_audio`) recorded as JSONL trace events. |
| **Timeline** | All processes' trace events merged on one clock; every metric is computed from it. |
| **Scenario** | A scripted run: fixtures + fault schedule + clock + number of users, executed by the runner. |
| **Fixture** | A versioned test input (audio clip or docs page) listed in a manifest with provenance and labels. |
| **Holdout** | Fixtures never used for tuning; run once to report results. |
| **Mock provider** | Scripted STT/LLM/TTS adapter used in tests and as the fault injector. |
| **Live provider** | Real STT/LLM/TTS adapter that spends money or credits. |
| **Pool** | A spending budget: `usd` (Deepgram + OpenRouter, $5.00 total) or `cartesia_credits` (≤ 16,000 used). |
| **Reservation** | Permission from the budget guard to spend up to an amount from a pool; live adapters cannot be built without one. |
