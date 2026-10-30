---
title: Troubleshooting
description: Fix the common VoiceCore failures, from a busy port and a blocked microphone to gateway close codes, budget refusals, missing audio, self-interruption and turns that end too early.
---

## Port 8080 is already in use

The gateway listens on `127.0.0.1:8080` by default, and Docker Compose publishes its gateway on the same address. If a Compose stack is still running, `go run ./cmd/gateway` cannot bind the port. It logs `gateway stopped` with an "address already in use" error and exits with status 1.

The quieter failure is worse. A client, a benchmark or this docs site can talk to the leftover Compose gateway without you noticing. That happened once in this project: the first live smoke run measured a leftover `docker compose` stack on port 8080 instead of the processes it had started. The WSS runner now stops if its own gateway or orchestrator fails to start.

To fix it, stop the old stack with `docker compose down`, or find what holds the port with `lsof -i :8080`. You can also run the gateway elsewhere, for example `go run ./cmd/gateway -addr 127.0.0.1:8081`. Then point the widget at it: set `data-endpoint`, `VITE_GATEWAY` for the demo, or `VOICECORE_GATEWAY` for this docs site.

## The microphone is blocked

When the browser refuses the microphone, the widget shows "Microphone access was blocked. You can still type your question below." The mic button is disabled and labelled "Microphone blocked", and focus moves to the text field.

The widget treats two browser errors as a refusal: `NotAllowedError`, when you or the browser denied the permission, and `SecurityError`. Any other error from the microphone leaves the button enabled, so you can try again.

To get voice back:

1. Allow the microphone for this site in your browser's site settings.
2. Reload the page. The mic button stays disabled for the rest of the page's life after a refusal; closing and reopening the panel does not re-enable it.
3. Open the widget and tap the mic button again.

You do not have to fix the microphone to use the assistant. Typed questions, up to 500 characters, get the same grounded answers and citations, and the session stays open for text.

## What the gateway close codes mean

The gateway closes the browser WebSocket with a code and a short reason text when something goes wrong. When it closes before the session starts, the widget shows "Could not connect" followed by `closed <code> <reason>`. After the session has started, it shows "Disconnected. Close and reopen to start again." The browser's developer tools show the same code on the WebSocket connection. Find the code in this table:

| Code | Reason text | Cause |
|---:|---|---|
| 1000 | session ended | normal end, after `session.ended` |
| 1007 | invalid frame | a malformed binary frame, or one that is not a 20 ms mic frame: wrong kind, not 320 samples, or a nonzero generation ID |
| 1008 | no hello, first message must be hello, invalid event | no valid `hello` within 5 s, or an unknown event type |
| 1008 | text.input text must be a short string | typed text longer than 500 characters, or not a string |
| 1008 | too many queued events | more than 256 client events waiting for the orchestrator |
| 1011 | orchestrator unavailable | the gateway could not reach the orchestrator within 5 s |
| 1013 | too many sessions | 50 live sessions in total, or 4 from your IP |
| 4001 | invalid or expired token | the token is older than 60 s, or was signed with another secret |
| 4002 | unsupported version or audio format | not version 1, 16 kHz mic, 20 ms frames and 24 kHz playout |
| 4003 | heartbeat missed | no message from the client for 10 s |

A 4001 after a gateway restart usually means the gateway picked a new random secret. Set `GATEWAY_SECRET` to keep one. A 1011 means the orchestrator is not running or not reachable at the gateway's `-upstream` URL, default `ws://127.0.0.1:8765`.

## HTTP errors before the WebSocket opens

Three gateway checks answer with an HTTP status before any WebSocket exists:

- **421 unknown host.** The request's `Host` header is not on the gateway's `-hosts` list, default `localhost,127.0.0.1,::1`. This blocks DNS rebinding. You see it when you reach the gateway through a LAN address or a custom host name. Add that name to `-hosts`, or pass an empty value to allow any host. The widget shows "Could not connect: token request failed (421)".
- **429 too many session requests.** One client IP asked `POST /v1/session` for more than 10 tokens in a minute. Wait, then reopen the panel. The widget shows "token request failed (429)".
- **403 on the token request or the WebSocket upgrade.** The page's origin is not on the `-origins` list, default `localhost:*,127.0.0.1:*`. Both the token endpoint and the WebSocket check it, so the widget cannot start. Add your site's host to `-origins`.

## The session ends with reason budget

This happens only with live providers. Every live session reserves its speech-to-text cap ($0.0385 for 300 s) and its language model cap ($0.02) from the `usd` pool before it starts. Its text-to-speech cap is reserved later, when it first speaks. If the ledger's total plus those reservations would pass the $5.00 project cap, the orchestrator refuses the session.

What you see:

- the orchestrator logs `session refused:` with the pool, the amount spent, the amount requested and the cap, and the fields `session_id` and `reason: budget`;
- the client receives `session.ended` with reason `budget`; the widget says "The session ended. Close and reopen to start again.";
- the gateway forwards that one `session.ended` and ends its side with the same reason.

Check `benchmarks/spend_ledger.json`. Its `totals` and `caps` fields show where each pool stands. Entries still marked `reserved` belong to sessions that never settled, for example after a crash, and count their full worst case. Mock providers never touch the ledger, so `--providers mock` always works.

## Spending limits inside one session

A live session can also reach one of its own caps while it runs. These caps are separate from the project pools: they stop one long or busy session from spending more than its share. The session itself stays open, and each cap produces a different symptom:

| Cap | What you notice |
|---|---|
| 300 s of speech sent to Deepgram | the agent says "Voice input has reached its limit for this session. You can keep typing your questions." Typed questions still work |
| $0.02 of language model use | the agent says "Sorry, I'm having trouble answering right now. Please try again." |
| 4,000 characters of speech with Deepgram Aura-2, or 1,500 with Cartesia | the agent says once "Spoken replies have reached their limit for this session, so I'll answer in text. Close and reopen me to talk again." Later answers arrive as text, unless one still fits in the characters left |

A new session gets fresh caps, as long as the project pools still cover them. Close the panel and open it again to start one. The caps live in the adapters: `MAX_AUDIO_S` in `deepgram_stt.py`, `LLM_CAP_USD` in `server.py` and `MAX_CHARS` in `deepgram_tts.py` or `cartesia_tts.py`.

## An answer appears but there is no audio

Check these causes in order:

1. **Mock providers.** Mock text-to-speech plays a 220 Hz tone, not speech. A tone means the audio path works. Start the orchestrator with `--providers live` for speech.
2. **Text-to-speech failed.** The text answer is always delivered first. If no audio of that answer was heard yet, the orchestrator retries speech once on a fresh stream; otherwise the answer stays text only.
3. **The speech cap or its pool ran out.** The session's characters are used up (4,000 with Deepgram Aura-2, 1,500 with Cartesia), or the pool cannot reserve them: `usd` for Deepgram, `cartesia_credits` for Cartesia. The agent says so once, and later answers arrive as text unless one still fits in the characters left.
4. **The answer was cancelled.** Speaking or typing while the agent plays cancels that generation. Its queued audio is dropped everywhere.

To see which one happened, run the orchestrator with `--trace-dir DIR` and the gateway with `-trace FILE`. Look for `tts` `error` or `retry` events, and for fence events with dropped frames. The gateway's `GET /debug/counters`, on its admin listener, shows `drops_fenced`.

## The agent interrupts itself

If the agent stops talking with nobody speaking, its own voice is reaching the microphone and being taken as a barge-in. VoiceCore has three defences against that echo:

- **Browser echo cancellation.** The SDK asks for the microphone with echo cancellation, noise suppression and automatic gain control on.
- **The echo gate.** While the agent plays, and for 200 ms after, a mic frame counts as speech only if the VAD is 0.2 more certain than usual and the mic's 100 ms power is at least the played power minus 6 dB. A barge-in also needs 160 ms of such speech.
- **No speech-to-text on echo.** During playback the recognizer hears nothing until you hold the floor, so echo is never transcribed into your next question.

Measured, this gave 0 of 4 false barge-ins on echo-only scripts (live, simulated room echo at −15 dB, n = 4). Loud laptop speakers without browser echo cancellation can break the −6 dB assumption. Lower the volume, or calibrate `echo_gate_db` in `turntaking/floor.py` for your device.

## A turn ends before you finish speaking

With live providers the default endpoint policy is eager:

- the orchestrator asks Deepgram to finalize after 200 ms of silence;
- a final transcript ending in a full stop, question mark or exclamation mark, with at least 200 ms of silence, ends the turn;
- without one, the turn ends after 800 ms of silence.

Deepgram sometimes punctuates a pause inside a question, so the turn ends early. This happened in 6 of 27 turns (live, n = 27). All 6 were repaired by the continuation merge: if you speak again within 2.5 s, before the answer is audible, the session cancels that answer and answers the whole question once.

The merge has a limit. Once the early answer is playing, new speech is a barge-in and a new question, and the first half is dropped. If you pause for long stretches mid-question, start the orchestrator with `--policy fixed`. It waits 800 ms of silence every time, and answered 15 of 15 questions in one piece (live, n = 15). Any turn also ends after 15 s of speech.

## The agent asks you to say that again

The agent says "Sorry, could you say that again?" in two cases:

- **No transcript.** After your turn ended, the speech-to-text returned no text within 5 s. Speak closer to the microphone or type the question.
- **The language model stalled.** No answer text arrived for 8 s. The reprompt replaces the missing answer.

Two other replies point at the language model provider:

- "I'm busy right now. Please try again in a moment." means OpenRouter returned HTTP 429 before any answer text, and retries after 1, 2 and 4 s did not help.
- "Sorry, I'm having trouble answering right now. Please try again." means another provider error, or the session's $0.02 language model cap was reached.

With mock providers, none of these replies come from a provider. The mock speech-to-text always returns its canned transcript.
