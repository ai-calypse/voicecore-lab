---
title: Use live providers
sidebar_label: Live providers
description: Add your provider keys, start VoiceCore with live speech and language providers, and see what each provider does, what a turn costs and how spending is capped.
---

## Add your provider keys to the env file

Live providers need three API keys. Copy the example file with `cp .env.example .env`, then fill in the values:

| Variable | Used for |
|---|---|
| `DEEPGRAM_API_KEY` | speech-to-text |
| `OPENROUTER_API_KEY` | the language model |
| `CARTESIA_API_KEY` | text-to-speech |
| `GATEWAY_SECRET` | optional fixed secret for gateway session tokens |

`.env` is gitignored. The orchestrator reads each key from the process environment first, then from `.env` at the repository root. Keys are never logged.

`GATEWAY_SECRET` belongs to the gateway, not the orchestrator. Without it, the gateway picks a random secret each time it starts, so tokens issued before a restart stop working. Mock mode needs none of these variables.

## Start VoiceCore with live providers

Pass `--providers live` to the orchestrator, or set `PROVIDERS` for Docker Compose:

```bash
uv run python -m voicecore.server --providers live   # by hand
PROVIDERS=live docker compose up                      # or the whole stack
```

Compose mounts `./benchmarks` into the orchestrator container, because live mode writes the shared spend ledger there. On Linux, run the container as your own user so it can write that folder: `HOST_UID=$(id -u) HOST_GID=$(id -g) PROVIDERS=live docker compose up`.

Live mode changes one default besides the providers. It uses the eager endpoint policy, while mock mode keeps fixed 800 ms. Choose a policy yourself with `--policy fixed`, `adaptive`, `asr_assisted` or `eager`. The gateway and the browser need no change: only the orchestrator talks to providers.

## What each live provider does

Each provider sits behind a typed streaming adapter in `services/agent-core/voicecore/providers/`.

| Provider | What VoiceCore uses it for | Price used by the budget |
|---|---|---|
| Deepgram nova-3 | Streaming speech-to-text of 16 kHz PCM16, with interim results. The orchestrator sends `Finalize` at its own endpoint, and keyterms such as "uv" and "uvx" help recognition | $0.0077 per minute |
| OpenRouter, `openai/gpt-oss-120b` | The grounded answer. Cerebras is tried first, with fallbacks allowed, at reasoning effort low and temperature 0 | $0.35 per million input tokens, $0.75 per million output |
| Cartesia sonic-3.6 | Streaming speech of the answer at 24 kHz, voice "Daniel", one context per generation | 1 credit per character |

Silero VAD and the fastembed embedding model run locally at no API cost. The Deepgram and Cartesia sockets, and the HTTPS connection to OpenRouter, open when a session starts, before you speak. Opening the Cartesia socket early cut TTS first audio from p50 456 ms to 145 ms (live, n = 15).

## How the spend guard works

The spend guard is `services/agent-core/voicecore/budget.py`. Every paid call reserves from a pool before it runs.

- **Two pools.** The `usd` pool covers Deepgram and OpenRouter, capped at $5.00 for the whole project. The `cartesia_credits` pool is capped at 16,000 of the 20,000 credits owned.
- **One ledger.** Reservations live in `benchmarks/spend_ledger.json`, written under a file lock, so concurrent sessions and harness runs share one total.
- **Worst case first.** A reservation is written immediately at its full amount. If a process crashes before it settles, the worst case still counts against the cap.
- **Settle on close.** When a session ends, each reservation is replaced with what was actually used.
- **No reservation, no adapter.** `providers/factory.py` refuses to build a live adapter without a reservation in the right pool, so nothing can spend outside the guard.

A reservation that would take a pool over its cap raises `BudgetExceeded`, and the session is refused.

## Per-session caps for speech, language and voice

Each live session has its own caps, reserved from the pools:

| Stage | Per-session cap | Reserved |
|---|---|---|
| Speech-to-text | 120 s of audio, which is $0.0154 at Deepgram's price | when the session starts |
| Language model | $0.006 | when the session starts |
| Text-to-speech | 1,500 characters, which is 1,500 credits | when the session first speaks |

Text-to-speech credits are reserved late so that idle sessions do not hold the credit pool. Opening the Cartesia socket early costs nothing.

When a session reaches a cap, its text path keeps working where it can:

- **STT cap:** the agent says "Voice input has reached its limit for this session. You can keep typing your questions."
- **LLM cap:** before each call, the adapter adds this prompt's worst case to what the session has spent. If that exceeds $0.006, the agent says it is having trouble answering.
- **TTS cap:** speech stops and answers arrive as text only.

If a pool cannot cover a new session's reservations, the session ends at once with reason `budget`.

## What a live turn costs

Two measured runs give the cost of one voice turn:

- **Before the latency work** (gpt-4.1-nano, live, n = 30 sessions): STT $0.00083, LLM $0.00013 and 138 Cartesia credits per turn.
- **After the latency work** (gpt-oss-120b on Cerebras, live, n = 29 turns): LLM $0.00057 per turn median, ranging from $0.00025 to $0.0012.

The model change made the LLM about four times dearer per turn, in exchange for a first token at p50 340 ms instead of 939 ms (live, n = 15). STT cost depends on how long the session's audio runs, at $0.0077 per minute. TTS cost is one credit per character of spoken answer.

The ledger is the source of truth. After the latency work on 2026-10-30, the project total was $0.95 of the $5.00 cap and 13,692 of the 16,000 Cartesia credits.

## Why provider keys never reach the browser

Provider keys stay on the server. Only the orchestrator reads them, and only the orchestrator calls Deepgram, OpenRouter and Cartesia.

The browser talks to the gateway alone. To start a session, the widget asks `POST /v1/session` for a token. The token is an expiry time signed with HMAC-SHA256 using the gateway's secret, and it is valid for 60 s. The browser sends it in its first WebSocket message, `hello`, and the gateway checks it there. After that, heartbeats keep the session open.

So the most a page visitor can see is a short-lived gateway token. It cannot be used to call a provider, and it expires a minute after it was issued.

:::warning
The token is for development only. It is not bound to a user, and the token endpoint allows any origin. Rate limits and session caps on the gateway bound the abuse, not the token.
:::

## Choose a different language model

Three orchestrator flags change the language model without code changes:

| Flag | Effect |
|---|---|
| `--llm-model` | the OpenRouter model ID; default `openai/gpt-oss-120b` |
| `--llm-provider` | the OpenRouter provider to try first; `any` lets OpenRouter route |
| `--llm-reasoning` | reasoning effort for reasoning models; `none` omits it |

The Cerebras pin and the low reasoning effort belong to the default model. When you pick another model, they are not applied to it.

To restore the earlier model:

`--llm-model openai/gpt-4.1-nano --llm-provider any --llm-reasoning none`

The adapter knows the prices of two models, gpt-oss-120b and gpt-4.1-nano. When it has to estimate the cost of any other model, it uses the dearer gpt-oss-120b prices.
