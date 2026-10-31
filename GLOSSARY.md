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
| **STT, LLM, TTS** | Speech-to-text (Deepgram nova-3), the language model (gpt-oss-120b on Cerebras via OpenRouter) and text-to-speech (Deepgram Aura-2). The three rented models. |
| **VAD** | Voice activity detection: a small local model (Silero) that says, frame by frame, whether someone is speaking. |
| **Echo gate** | The check that stops the agent's own voice, leaking from the speakers into the mic, from counting as the user talking. |
| **Grounding** | Releasing an answer sentence only once it carries a valid citation to a retrieved docs passage. |
| **Hybrid search** | Keyword search (SQLite FTS5) and vector search (local embeddings) run on the same question; their ranked lists are merged by **reciprocal rank fusion (RRF)**. |
| **Session token** | A single-use, 60-second credential the gateway issues to a browser, bound to its IP by an HMAC. Provider keys never leave the server. |
| **Resume key** | A 32-byte secret sent in `welcome`. A reconnect must present it to rejoin a session; knowing the session id alone is not enough. |
| **Circuit breaker** | After repeated failures from one provider or orchestrator, stop calling it for a while and fail fast instead of slowly. |
| **Liveness / readiness** | `/healthz` answers "the process is alive"; `/readyz` answers "send me new users". |
| **Drain** | Graceful shutdown: take no new sessions, let open ones finish, settle their spend, then exit. |
| **Copy** | One running gateway or orchestrator process when several run behind a load balancer. |
| **Public pool** | A capped sub-budget inside `usd` for a public demo ($2 total, $0.50 a day). When it is spent, answers switch to a free text-only mode. |
