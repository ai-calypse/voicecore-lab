# ADR 0001: Engine ownership

**Status:** Accepted, 2026-10-29. **Task:** S00-T04. **Supersedes:** nothing.

**Context.** VoiceCore Lab exists to show real-time voice engineering a reviewer can inspect. A hosted end-to-end voice agent hides exactly that work (turn-taking, cancellation, transport, latency accounting), so it can only be a comparison point. This record states what we write, what we buy, and what we deliberately do not build. Module paths and seams are in [the build plan](../IMPLEMENTATION_PLAN.md#b-module-map).

## Owned code

Written and tested in this repository:

- **Browser SDK (TypeScript):** AudioWorklet capture, resampling to 16 kHz, PCM16 framing, the WebSocket session client, and ordered playout with cancel/fence flush and playout events.
- **Wire protocol:** one binary frame format and one set of JSON control events for both hops (browser↔gateway, gateway↔orchestrator), with golden test vectors shared by TS, Go and Python.
- **Real-time gateway (Go):** connection ownership: token auth, hello/format negotiation, heartbeat, resume window, bounded queues with drop/gap counters, and the outbound generation fence.
- **Orchestrator (Python asyncio):** the turn-taking module (endpoint policies, echo gating, barge-in) and the generation runtime (generation IDs, stale-result checks, transcript assembly, TTS chunking and ordering, recovery rules).
- **Provider adapters:** typed streaming STT, LLM and TTS interfaces with mandatory mock adapters and one live adapter each; the budget guard every live adapter must pass.
- **Answer engine:** docs ingestion, FTS5 + embedding retrieval with reciprocal rank fusion, the `docs.search` tool, citation validation, and shared text/voice answers.
- **Evidence tooling:** fixture builder, scenario runner, trace timeline, benchmarks and evaluation reports.

## Purchased inference

Used through replaceable adapters, never claimed as our work:

| Capability | Provider / model | Notes |
|---|---|---|
| Streaming STT | Deepgram nova-3 streaming, `Finalize` at our endpoint, keyterms for uv vocabulary (confirmed 2026-10-30; $0.0077/min) | `DEEPGRAM_API_KEY`; per-session cap 120 s |
| LLM | OpenAI `openai/gpt-4.1-nano` via OpenRouter's OpenAI-compatible API | cheapest non-reasoning OpenAI model with streaming + tools on 2026-10-29 ($0.10 / $0.40 per M tokens) |
| Streaming TTS | Cartesia `sonic-3.6`, voice "Daniel" (`47c38ca4…`), WebSocket API version 2026-08-14, one context per generation (confirmed 2026-10-30) | 1 credit per character; 20,000 owned, plan uses ≤ 16,000; per-session cap 1,500; Cartesia allows 2–5 concurrent TTS requests depending on plan |
| VAD model | Silero VAD (ONNX) | runs locally |
| Embeddings | fastembed small ONNX model | runs locally, no API cost |
| Fixture voices | LibriSpeech (CC BY 4.0); Deepgram Aura-2 for docs questions | Aura clips kept local, not committed |

Money cap for all paid use: $5.00 total for the project, including $0.525 already spent (enforced by `voicecore/budget.py`).

## Baseline only

The Deepgram Voice Agent API (hosted STT → LLM → TTS) was measured in S00-T02 (`harness/baseline_deepgram.py`, `benchmarks/baseline_results.json`) and will be re-run once at the Step 03 comparison gate. It is a control for latency and turn success under matched conditions. It is not, and must not become, the runtime: no orchestration, turn-taking or cancellation logic may be delegated to a managed voice-agent product.

## Non-goals

Commercial billing and pricing, SaaS plans, tenant isolation, complex admin UI, CRM integrations, private org knowledge sources, voice cloning, training speech foundation models, a distributed SFU, a 99.99% production SLO, telephone carrier certification, on-device inference as core delivery, and unmeasured latency claims (from the master plan's explicit non-goals). SIP/telephony stays a design document unless a real integration is built and tested.

## Architecture decisions 2026-10-29

Adopted by the user after an improve-codebase-architecture review of the planned layout:

1. **One generation runtime + fencing.** Session state, streaming, TTS ordering, cancellation and recovery live in one Python module. Every agent frame carries a generation ID, and every queue owner (Python, Go, browser) drops frames at or below the cancelled generation.
2. **One turn-taking module inside the orchestrator.** VAD, endpointing, echo gating and barge-in answer one question (who holds the floor) and share session state, so they are not a separate service.
3. **Client playout module + one harness runner and timeline.** Ordered playout, flush on cancel and the silence ACK live in the SDK. Scenarios, chaos, benchmarks and evals share one runner, and every metric is computed once from one merged trace timeline.
4. **No reorder buffer on the WebSocket path.** A single WebSocket runs over TCP and cannot reorder frames; the gateway keeps bounded queues and counters, and the reorder/seq-wrap jitter buffer moves to the Step 07 RTP lab, where packets really do reorder.
