---
title: Providers reference
sidebar_label: Providers
description: The STT, LLM and TTS provider contracts, the error kinds, each live adapter (Deepgram STT and TTS, OpenRouter, Cartesia) with its settings and prices, how to switch the LLM and the TTS, and the mock providers.
---

VoiceCore treats speech recognition, the language model and speech synthesis as replaceable providers. The orchestrator talks to each one through a small contract in `services/agent-core/voicecore/providers/base.py`. Live adapters and mock adapters implement the same contracts, so the session runtime cannot tell them apart. This page documents the contracts, every live adapter and the mocks.

## Three provider contracts

There are three provider contracts, written as Python `Protocol` classes in `providers/base.py`:

- `STTStream`: streaming speech-to-text. Audio goes in, partial and final transcripts come out.
- `LLM`: a streaming chat model. Messages go in, text deltas, tool calls and a done marker come out.
- `TTSStream`: streaming text-to-speech. Text goes in per generation, audio comes out per generation.

Audio is always PCM16 little-endian mono: 16 kHz into the STT, 24 kHz out of the TTS. Those are the same rates as the mic and agent frames of the wire protocol, so no resampling happens in the orchestrator.

Live adapters are only ever built through `make_live(kind, reservation)` in `providers/factory.py`. It refuses to build an adapter without a budget reservation from the right pool: `usd` for STT, LLM and Deepgram TTS, `cartesia_credits` for Cartesia TTS. So no live adapter can spend outside the budget guard.

## The STTStream contract

A speech-to-text stream has four methods:

| Method | What it does |
|---|---|
| `send(pcm)` | send 16 kHz PCM16 audio |
| `finalize()` | our endpoint: flush and return finals for the audio so far |
| `events()` | async iterator of `Partial(text)` and `Final(text, speech_final)` |
| `close()` | close the stream |

`finalize()` exists because VoiceCore owns endpointing. The session decides when the user has finished speaking, with Silero VAD and its own policy, and then asks the STT for the final transcript at once instead of waiting for the provider's own endpoint. `Final.speech_final` carries the provider's own end-of-speech flag, but VoiceCore does not rely on it.

An STT stream can also have an optional `warm()` method. The session calls it at session start, so the connection is open before the user speaks.

## The LLM contract

The language model contract has one method:

```python
def stream(self, messages: list[dict], tools: list[dict] | None = None, max_tokens: int = 80) -> AsyncIterator[TextDelta | ToolCall | Done]: ...
```

- `messages` are chat messages in the OpenAI shape, `{"role": ..., "content": ...}`.
- `TextDelta(text)` is a piece of the answer as it streams.
- `ToolCall(id, name, arguments)` is a tool call, with `arguments` as the JSON text the model wrote.
- `Done(usage)` ends the stream. `usage` has `input_tokens`, `output_tokens` and `cost_usd` when known.

The contract's default `max_tokens` is 80, but the grounded answer engine (`AnswerEngine`) passes 200, because the default model counts its reasoning tokens against the limit. Like the STT, an LLM adapter may have a `warm()` method that the session calls at session start.

## The TTSStream contract

A text-to-speech stream has four methods, all keyed by generation id:

| Method | What it does |
|---|---|
| `synth(gen, text, last)` | speak `text` as part of generation `gen`; `last` marks the end of the generation |
| `audio()` | async iterator of `Audio(gen, pcm, last)`: 24 kHz PCM16, with an empty `pcm` on the last item of a generation |
| `cancel(gen)` | stop generation `gen` and every older one |
| `close()` | close the stream |

The session cuts the streaming answer at sentence ends (`Chunker` in `runtime/text.py`) and sends each sentence to TTS as soon as it is complete, so audio can start before the answer is. Audio within one generation arrives in the order the text was sent. After `cancel(gen)`, no audio of that generation or an older one may come out of `audio()`. That is the same fence rule as the wire protocol, applied inside the adapter.

## Provider error kinds

Every provider adapter reports failures as `ProviderError(kind, message)`, with one of three kinds:

- `retryable`: try again, for example after a dropped connection or an HTTP 5xx.
- `rate_limited`: back off, for an HTTP 429.
- `fatal`: do not retry, for any other HTTP 4xx or a per-session budget cap.

`http_error(status, message)` in `providers/base.py` maps HTTP statuses to these kinds.

How the session reacts:

- **LLM, rate limited before any answer text:** the session waits 1, 2, then 4 s and tries again. If all retries fail, the agent says it is busy.
- **LLM, any other failure, or no token for 8 s:** the agent says it is having trouble, or asks the user to repeat after a stall. The turn always ends with an answer.
- **TTS failure:** the text answer is still delivered. The session retries speech once on a fresh TTS stream, but only if none of that answer was heard yet and the error was not fatal. After a fatal TTS error, such as the per-session character cap, the agent says once, as a text reply, that spoken replies have reached their limit and it will answer in text.
- **STT fatal, such as the 300 s cap:** the agent says voice input has reached its limit; typing still works. There is no STT reconnect.

## Deepgram streaming STT adapter

`DeepgramSTT` in `providers/deepgram_stt.py` streams audio to Deepgram's live transcription WebSocket, `wss://api.deepgram.com/v1/listen`, authenticated with `DEEPGRAM_API_KEY`. The connection parameters are fixed in `PARAMS`:

| Parameter | Value |
|---|---|
| `model` | `nova-3` |
| `encoding`, `sample_rate`, `channels` | `linear16`, 16000, 1 |
| `interim_results` | true |
| `punctuate`, `smart_format` | true |
| `endpointing` | 300 (Deepgram's own; VoiceCore does not rely on it) |
| `keyterm` | `VoiceCore`, `endpointing`, `barge-in`, `Silero`, `VAD`, `Deepgram`, `Cartesia`, `OpenRouter`, `Cerebras`, `gpt-oss`, `WebSocket`, `WebRTC`, `jitter buffer`, `Docusaurus` |

Punctuation matters: the eager endpoint policy ends a turn on a final that ends in `.`, `?` or `!`.

Cost is counted from the audio sent: $0.0077 per minute (nova-3 streaming, pay as you go, deepgram.com/pricing, checked 2026-10-29). Each session may send at most 300 s of audio (`MAX_AUDIO_S`), which is $0.0385; past that, `send` raises a fatal error. The session sends only speech: 300 ms before the first voiced frame and 600 ms after the last.

## How the Deepgram adapter uses Finalize, KeepAlive and CloseStream

The Deepgram adapter uses three Deepgram control messages:

- **`Finalize`** is sent by `finalize()`. The session calls it at its own endpoint, or with eager endpointing after 200 ms of VAD silence, once per pause. Deepgram then returns the final transcript for the audio so far, about 100 ms later in the endpoint study.
- **`KeepAlive`** is sent every 4 s when no audio has been sent for 4 s. Deepgram closes a socket that gets no audio for 10 s, which happens after the mic is revoked or during long silences, since silence is not sent.
- **`CloseStream`** is sent by `close()`. Deepgram then flushes any remaining finals and a metadata message; the adapter waits up to 10 s for them.

`warm()` opens the socket at session start, because the handshake took about 250 ms. If warming fails, the first `send` connects instead. If the stream ever closes on an interim transcript with no final, the adapter keeps those words as a final, a case seen once live. The Deepgram request id is recorded for the spend ledger.

## Why the Deepgram adapter boosts keyterms

The STT adapter sends keyterms for the words of the docs the assistant answers from: VoiceCore, endpointing, barge-in, Silero, VAD, the provider names, gpt-oss, WebSocket, WebRTC, jitter buffer and Docusaurus. nova-3 supports keyterm prompting, which raises the chance that these words are recognised.

The reason was measured on the earlier corpus, the uv docs, whose keyterms were `uv`, `uvx`, `uv sync`, `uv lock` and `pyproject.toml`. In the first live breakdown run (live, n = 10 questions), Deepgram transcribed "uv" wrongly in 5 of 10 questions: as "of", "OV", "u v", and "uv sync" as "OfSync". After adding the keyterms, every question in the next live run that names uv was transcribed with "uv" (`reports/perf.md`, 15 dev docs questions).

The keyterms are fixed in `PARAMS` in `providers/deepgram_stt.py`. If you point the assistant at docs about another product, add that product's names and commands there. There is no flag for it.

## OpenRouter LLM adapter

`OpenAICompatLLM` in `providers/openai_compat_llm.py` streams chat completions from OpenRouter (`https://openrouter.ai/api/v1`) with the OpenAI Python SDK and `OPENROUTER_API_KEY`. Its defaults since the latency work of 2026-10-30:

- **Model** `openai/gpt-oss-120b`.
- **Provider order** Cerebras first, with `allow_fallbacks: true`, so a Cerebras outage makes turns slower instead of failing.
- **Reasoning effort** `low`.
- **Temperature** 0, and `max_tokens` 200 from the answer engine, which covers reasoning tokens too.
- **Usage reporting** on, so OpenRouter returns the call's cost.

The SDK's own retries are off (`max_retries=0`); the session's retry policy applies instead. All LLM adapter instances in a process share one `httpx` connection pool per event loop, with a 60 s keep-alive and a 30 s timeout, so a turn does not pay a fresh TLS handshake. `warm()` sends a free `GET /key` request at session start to open that connection. In the first-token benchmark (`harness/llm_ttft.py`), gpt-oss-120b on Cerebras at effort low gave the first answer token at p50 300 ms, against 574 ms for gpt-4.1-nano on the same grounded prompt (live, text only, n = 6 each).

## How the LLM adapter counts cost

The LLM adapter tracks what each session spends:

- When OpenRouter's usage report includes a cost, the adapter uses it.
- Otherwise it computes the cost from the token counts and the price table below.
- A call that ends before its usage report arrives, because it was cancelled or failed, is still billed. The adapter estimates it at about 4 characters per token for the prompt and the text received so far.

Before every call, the adapter checks the cost so far plus this prompt with a worst-case output of `max_tokens` × 4 characters. If that would pass the session's reservation ($0.02, `LLM_CAP_USD` in the server), the call fails as fatal before anything is sent.

| Model | Input, USD per million tokens | Output, USD per million tokens |
|---|---:|---:|
| `openai/gpt-4.1-nano` | 0.10 | 0.40 |
| `openai/gpt-oss-120b` (Cerebras) | 0.35 | 0.75 |

These are OpenRouter endpoint prices recorded in `PRICES` on 2026-10-30. A model that is not in the table is priced at the dearest row. Measured live, gpt-oss-120b cost $0.00057 per turn (median over 29 turns).

## Switch the LLM with orchestrator flags

Three orchestrator flags change the LLM without code changes. They only apply with `--providers live`:

- `--llm-model <OpenRouter model id>` picks the model. The default is `openai/gpt-oss-120b`.
- `--llm-provider <name>` picks the OpenRouter provider to try first. `any` lets OpenRouter route.
- `--llm-reasoning <effort>` sets the reasoning effort (`low`, `medium` or `high`). `none` omits it, for models without reasoning.

The Cerebras pin and the `low` effort belong to the default model. If you change `--llm-model` and leave the other two unset, the adapter sends no provider order and no reasoning setting. To restore the model used before the latency work:

```bash
uv run python -m voicecore.server --providers live \
  --llm-model openai/gpt-4.1-nano --llm-provider any --llm-reasoning none
```

Through the benchmark runner, pass each flag with `--server-arg`. After a model change, re-run the answer eval: [Tune latency](../guides/tune-latency.md) shows how.

## Deepgram Aura-2 streaming TTS adapter

`DeepgramTTS` in `providers/deepgram_tts.py` is the default text-to-speech adapter. It streams speech from Deepgram over one WebSocket per session, `wss://api.deepgram.com/v1/speak`, authenticated with the same `DEEPGRAM_API_KEY` as the STT:

- **Model** `aura-2-thalia-en`.
- **Output** `linear16` at 24000 Hz, which becomes 20 ms agent frames directly.
- **Messages** `Speak` carries text and `Flush` asks for its audio. Binary audio follows, then `Flushed`. `Clear` drops buffered text and audio, and Deepgram confirms it with `Cleared`.

Cost is counted per character sent: $0.030 per 1,000 characters (Aura-2 pay as you go, deepgram.com/pricing, checked 2026-10-30), billed in the `usd` pool. Each session may speak at most 4,000 characters (`MAX_CHARS`). The session reserves that worst case, $0.12, when it first speaks, and settles it to the actual use when it ends.

The socket opens at session start through `open_socket()`, which costs nothing. If Deepgram closed the socket while it sat idle, the next `synth` opens it again. If a TTS failure leads to a retry on a second stream, both streams bill the same reservation and share its character cap.

## How the Deepgram TTS adapter tracks generations

Deepgram's speak stream has no context per generation, and its audio frames carry no generation tag. The adapter sends text one generation at a time and keeps the unfinished generations in the order their text was sent. Every audio frame belongs to the oldest unfinished generation.

Flush messages decide when audio starts and when a generation ends:

- After a generation's first chunk, the adapter sends `Speak` then `Flush`, so the first sentence is spoken at once instead of waiting for more text.
- Middle chunks go out as `Speak` only.
- After the last chunk, it sends `Speak` then `Flush` again. The `Flushed` that answers this last Flush ends the generation, and the adapter emits its last item with no audio.

A usual answer therefore costs about 2 Flushes. Deepgram allows 20 Flushes per 60 s and 2,000 characters per `Speak`, so longer text is split over several `Speak` messages. A `Warning` or `Error` message from Deepgram is recorded, not raised. If the socket closes while audio is still due, the stream fails with a retryable error, and the session may retry speech once.

## How the Deepgram TTS adapter cancels an answer

Deepgram holds text until a Flush. Text of a cancelled answer that was sent but not flushed would otherwise be spoken together with the next answer. So `DeepgramTTS.cancel(gen)` does three things:

1. It sets its fence to `max(fence, gen)` and removes every generation at or below the fence from its unfinished generations and pending Flushes.
2. If one of those generations was unfinished and the socket is open, it sends `Clear`, which drops Deepgram's buffered text and audio.
3. Until Deepgram answers with `Cleared`, it drops every audio frame and ignores `Flushed`, because that audio belongs to cancelled text.

From then on, `audio()` drops every item of a generation at or below the fence, and `synth()` ignores text for one. The orchestrator, the gateway and the browser each check the fence again before anyone could hear late audio. A live contract test checks that a cancelled answer's unflushed text is never spoken with the next answer (`reports/latency_tuning.md`).

## Switch the TTS provider with an orchestrator flag

The `--tts` orchestrator flag picks the text-to-speech provider. It only applies with `--providers live`:

- `--tts deepgram`, the default, uses Deepgram Aura-2. It bills the `usd` pool at $0.030 per 1,000 characters, with at most 4,000 characters per session.
- `--tts cartesia` uses Cartesia sonic-3.6. It bills the `cartesia_credits` pool at 1 credit per character, with at most 1,500 characters per session, and needs `CARTESIA_API_KEY`.

```bash
uv run python -m voicecore.server --providers live --tts cartesia
```

Deepgram became the default on 2026-10-30, because Cartesia's 1,500-character session cap ran out after about 6 spoken answers in a manual session. Both adapters open their socket at session start and reserve their budget only when the session first speaks. TTS first audio was p50 115 ms with Deepgram Aura-2 (live, n = 6) and p50 145 ms with Cartesia sonic-3.6 (live, n = 15), in two separate runs of the same stack.

## Cartesia streaming TTS adapter

`CartesiaTTS` in `providers/cartesia_tts.py` is the alternative text-to-speech adapter, used with `--tts cartesia`. It streams speech from Cartesia over one WebSocket per session, `wss://api.cartesia.ai/tts/websocket` with `cartesia_version=2026-08-14`, authenticated with `CARTESIA_API_KEY`:

- **Model** `sonic-3.6`, **voice** "Daniel" (id `47c38ca4-5f35-497b-b1a3-415245fb35e1`), language `en`.
- **Output** raw `pcm_s16le` at 24000 Hz, which becomes 20 ms agent frames directly.
- **One context per generation.** Every `synth` call sends `context_id` `g<gen>` with `continue: true`, except the last piece of a generation. Within one context, audio arrives in the order the text was sent.

Credits are counted per character: 1 credit per character, with at most 1,500 characters per session (`MAX_CHARS`). The session reserves those 1,500 credits when it first speaks, not when it opens. The socket itself opens at session start through `open_socket()`, which costs nothing, because the handshake took 250 to 330 ms. If a TTS failure leads to a retry on a second stream, both streams bill the same reservation and share its character cap.

## Cartesia cancel semantics

Cancelling speech on Cartesia needs care, because Cartesia's cancel only stops requests that have not started generating. Audio for text that is already being synthesised can still arrive after the cancel.

So `CartesiaTTS.cancel(gen)` does two things:

1. It sets its fence to `max(fence, gen)` and sends Cartesia a cancel for context `g<gen>`.
2. From then on, `audio()` drops every item of a generation at or below the fence, and `synth()` ignores text for one.

An error message from Cartesia ends only its own generation: the adapter emits that generation's last item with no audio, records the error, and keeps the socket for later generations. Only a closed socket fails the stream as a whole, as a retryable error.

The orchestrator also checks every audio item against its own fence before framing it, and the gateway and browser fence again. With `--tts cartesia`, a late Cartesia chunk is therefore dropped in up to four places before anyone could hear it.

## Mock providers

`providers/mock.py` has scripted mock adapters for every contract. They need no keys and spend nothing, and they double as the fault injector for tests: delays, errors and stalls come from the script.

- **`MockSTT`** emits scripted `Partial` and `Final` events once enough audio has been received (audio time, not wall time). With `canned` text, it returns that text as a `Final` on every `finalize()`.
- **`MockLLM`** plays an `LLMScript`: first token after `first_token_ms` (default 200), then one token every `token_ms` (default 15). The script can also raise an error, stall after N tokens, or emit tool calls.
- **`MockTTS`** synthesises a 220 Hz tone, 60 ms per character, in 20 ms items, after `first_audio_ms` (default 150). It can play a given audio clip instead, for barge-in scenarios.

With `--providers mock`, the server uses a canned transcript ("how does eager endpointing work?") and one scripted answer with two citations. Because the mock STT returns its final at every pause, mock mode uses fixed 800 ms endpointing. The fake-time benchmark and the CI gate run on these mocks.
