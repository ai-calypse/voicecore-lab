---
title: Frequently asked questions
sidebar_label: FAQ
description: Short answers to common questions about VoiceCore, the voice assistant on this site, its providers, its cost and its speed.
---

## Questions about VoiceCore

### Is VoiceCore a hosted voice agent product?

No. VoiceCore Lab is a voice AI systems engineering portfolio: a real-time voice agent whose transport, turn-taking, cancellation and latency accounting you can read and test. It runs as three processes you start yourself, a browser SDK, a Go gateway and a Python orchestrator. There is no hosted service, no billing, no SaaS plans and no tenant isolation; ADR 0001 lists these as non-goals. The hosted Deepgram Voice Agent API appears only as a latency baseline, and no orchestration, turn-taking or cancellation is delegated to it. See the [introduction](intro.md) for what VoiceCore builds and what it buys.

### Can I run VoiceCore without API keys?

Yes. Mock providers are the default, need no keys and spend nothing. Run `docker compose up --build` and open `http://localhost:5173`, or start the three processes by hand. In mock mode the speech-to-text returns a canned transcript, the language model streams a scripted cited answer, and the text-to-speech plays a 220 Hz tone instead of speech. Voice activity detection, turn-taking, the generation runtime, retrieval, the gateway and the browser playout are all real. The [quickstart](getting-started/quickstart.md) has the commands. Live providers need three keys in `.env`.

### Which parts can I swap for another provider?

Speech-to-text, the language model and text-to-speech each sit behind a typed streaming adapter in `services/agent-core/voicecore/providers/`. Every kind has a mock adapter and a live adapter: Deepgram nova-3, an OpenAI-compatible chat client pointed at OpenRouter, and Deepgram Aura-2. Text-to-speech has a second live adapter, Cartesia sonic-3.6, picked with `--tts cartesia`. The language model is the easiest to change. The `--llm-model`, `--llm-provider` and `--llm-reasoning` flags pick any OpenRouter model without code changes. A new speech provider needs a new adapter. One contract test suite runs against the mock and live adapters alike, and `providers/factory.py` builds a live adapter only against a budget reservation.

### Is my audio stored?

No audio is written to disk by the gateway or the orchestrator. Audio passes through the gateway's bounded queues to the orchestrator, which sends speech to Deepgram during live sessions. Traces are optional: the gateway writes them with `-trace` and the orchestrator with `--trace-dir`. They record timings, stages and counters. They hold no transcript or answer text unless a run explicitly sets `include_text`. The widget's footer states that audio is not stored. Closing the panel ends the session, turns the microphone off, closes the audio and the socket, and clears the conversation from the page.

## Questions about the assistant on this site

### What can the assistant on this site answer?

It answers questions about these docs, and only from these docs. A documentation question gets two or three short spoken sentences, and each sentence cites the section that supports it, shown as [1], [2] and so on. A greeting, a thank-you or "what can you do?" gets a short friendly reply without citations that names topics these docs cover. When the docs do not cover something, it says so in a friendly way and suggests the closest topic they do cover. It never uses outside knowledge for facts. Sentences without a valid citation are held back, and a citation to a passage that was not retrieved is removed before you hear it.

### Why did the page change when the assistant answered?

The assistant opens the section it cites. When an answer cites a section, the widget dispatches a `voicecore:navigate` event with the section's URL and title. This docs site handles it in `src/theme/Root.jsx`. It changes the route without reloading the page, scrolls to the cited heading and highlights that section. Because the page does not reload, the voice session keeps running, and you can ask a follow-up straight away. On a site that does not handle the event, the citation links open in a new tab instead. [Embed the widget](getting-started/embed-the-widget.md) shows how to handle the event on your own site.

### Does the assistant remember my earlier questions?

Yes, within one session. The orchestrator keeps the recent turns of the conversation and passes them to the language model as context, so a follow-up question can refer to an earlier answer. The facts in each answer still come only from the passages retrieved for that question. The memory lasts as long as the session. Closing the panel, leaving the page or reaching the 15-minute session limit ends it, and a new session starts with no history. Navigating between pages of this site after a citation does not end the session.

### Can I interrupt the assistant while it is talking?

Yes. Start talking and the agent's audio stops. This is barge-in. Measured, the agent went silent at p50 303 ms after the user started speaking, and 8 of 8 interruptions were silenced (live, n = 8). Typing a new question while it speaks also cancels the current answer. Either way, the cancelled generation's audio is dropped in the orchestrator, the gateway and the browser, so none of the old answer plays afterwards. If the assistant ends your turn too early while you pause, see [troubleshooting](guides/troubleshooting.md).

## Questions about cost and speed

### How fast does VoiceCore answer?

From the moment you stop speaking to the first agent audio playing, VoiceCore measured p50 841 ms and p95 1,520 ms (live, n = 15). Before the latency work, the same 15 questions took p50 2,317 ms (live, n = 15). The gain came from four changes: an eager endpoint, `openai/gpt-oss-120b` on Cerebras, a warm HTTP connection and an early TTS socket. With live providers, the end of your turn is detected at p50 340 ms and the first language model token arrives at p50 340 ms (live, n = 15). The hosted Deepgram Voice Agent measured 972 ms (live, n = 3). These are small samples on one laptop; they rank design choices, not production rates.

### How much does one question cost with live providers?

One voice turn cost about $0.00083 for speech-to-text and 138 Cartesia credits for speech (live, n = 30 sessions, measured before the model change). With the current language model, the LLM part costs $0.00057 per turn median, between $0.00025 and $0.0012 (live, n = 29 turns). Speech now defaults to Deepgram Aura-2 at $0.030 per 1,000 characters; its per-turn cost has not been measured. Each session is capped at 300 s of speech-to-text, $0.02 of language model and 4,000 characters of speech, or 1,500 with Cartesia. The whole project is capped at $5.00 and 16,000 Cartesia credits. The spend guard in `voicecore/budget.py` enforces these caps by reserving the worst case before any paid call. See [live providers](getting-started/live-providers.md).

### How many people can talk to it at once?

The gateway allows at most 50 live sessions in total and 4 per client IP by default; beyond that a new session closes with code 1013. Its `-max-sessions` and `-max-sessions-per-ip` flags change those limits. Measured with mock providers, 40 of 40 concurrent sessions completed with p95 1,305 ms and no gateway drops (mock, n = 40). CPU was not profiled, so the ceiling is unknown. With live providers, only 2 concurrent sessions were tested, and both completed (live, n = 2). That test used Cartesia, which allows 2 to 5 concurrent speech requests depending on the plan.
