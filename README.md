# VoiceCore Lab

A real-time voice assistant for a documentation site, built to show the systems work underneath voice AI: browser audio capture and playout, a Go real-time gateway, turn-taking with an echo gate, barge-in that silences the agent, a grounded answer engine, and the tracing and benchmarks that measure all of it.

Speech-to-text, the language model and text-to-speech are bought (Deepgram nova-3, `openai/gpt-oss-120b` on Cerebras via OpenRouter, Deepgram Aura-2; Cartesia sonic-3.6 with `--tts cartesia`) through replaceable adapters. Everything between the microphone and the speaker is this repository's code. [ADR 0001](docs/adr/0001-engine-ownership.md) draws that line.

```mermaid
flowchart LR
  B[Browser SDK: AudioWorklet capture, 16 kHz PCM16 frames, ordered playout] <-->|one binary + JSON protocol| G[Go gateway: token, heartbeat, resume, bounded queues, generation fence]
  G <-->|same protocol| O[Python orchestrator: Silero VAD + floor, generation runtime, grounded answers]
  O <--> P[Deepgram STT / OpenRouter LLM / Deepgram TTS]
```

## Results (labelled; details and commands in each report)

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="reports/latency_chart_dark.png">
  <img alt="Stage medians of one voice turn. Now, live with the eager endpoint and gpt-oss-120b on Cerebras: 340 ms to detect the end of the turn, 340 ms LLM first token, 145 ms TTS first audio, 841 ms total. Before, live with the fixed 800 ms endpoint and gpt-4.1-nano: 861, 939, 456 ms, 2,317 ms total. Before, ASR-assisted endpointing: 523, 1,289, 406 ms, 2,259 ms total. Mock providers with 40 sessions: 820, 314, 150 ms, 1,296 ms total. A dashed line marks the hosted Deepgram Voice Agent median, 972 ms." src="reports/latency_chart_light.png">
</picture>

| What | Result | Label | Source |
|---|---|---|---|
| User stops speaking → first agent audio rendered | p50 841 ms, p95 1,520 ms (n = 15); 2,317 ms before tuning | live-provider | [reports/latency_tuning.md](reports/latency_tuning.md) |
| …of which detecting the end of the turn (eager endpoint) | p50 340 ms; 6/27 early cutoffs merged before any audio played | live-provider | [ADR 0002](docs/adr/0002-turn-policy.md) |
| Same path with mock providers | p50 1,320 ms, p95 1,440 ms (n = 216) | fake-provider | [reports/perf.md](reports/perf.md) |
| Barge-in: user starts talking → agent audio stops | p50 303 ms (8/8 silenced), 0/4 false barge-ins on echo | live-provider | [reports/barge_in.md](reports/barge_in.md) |
| Gateway overhead per round trip (two passes) | 0.19 ms median | measured, loopback | [benchmarks/transport.md](benchmarks/transport.md) |
| Grounded answers on held-out questions (gpt-oss-120b) | refusals 14/15 right, citations 12/12 supporting | live-provider | [reports/docs_eval.md](reports/docs_eval.md) |
| Docs assistant on the docs site, 22 scripted cases (gpt-oss-120b, text) | small talk 4/4 friendly and uncited; off-topic 4/4 declined; docs questions 14/14 answered with citations, 10/14 opened the predicted page (the other 4 opened another section that answers it) | live-provider | [reports/assistant_eval.json](reports/assistant_eval.json) |
| Adversarial docs (stale, contradicting, injected, unauthorised) | 14/15 pass, 0 leaked claims | live-provider | [reports/docs_eval.md](reports/docs_eval.md) |
| STT word error rate, held-out audio | 6.5 % (n = 25) | live-provider | [reports/quality_eval.md](reports/quality_eval.md) |
| Concurrent sessions, mock providers | 40/40 complete, p95 1,305 ms, 0 drops | fake-provider | [reports/perf.md](reports/perf.md) |

Samples are small (10–30 live turns per number), so these rank design choices; they are not production rates. The hosted Deepgram Voice Agent measured 972 ms (n = 3, [reports/latency_breakdown.md](reports/latency_breakdown.md)); what closed the gap is in [reports/latency_tuning.md](reports/latency_tuning.md).

## Quick start (no keys, no spend)

```bash
docker compose up --build        # gateway :8080, orchestrator, docs :3000, demo :5173 — mock speech and language providers
open http://localhost:3000       # the docs site; "Ask the docs" answers from it and opens the section it cites
open http://localhost:5173/?lab=1  # a session timeline
uv run python harness/smoke.py   # optional: one typed question over the WebSocket, expects a cited answer
```

The first build embeds the docs snapshot into the orchestrator image (a few minutes).

## Develop

Requirements: Go ≥ 1.25, Node 24 with pnpm 11, Python 3.12 with [uv](https://docs.astral.sh/uv/), ffmpeg (only to rebuild audio fixtures).

```bash
uv sync && pnpm install
make test        # Go (race + synctest), Python (pytest, fake time), TypeScript (vitest): no network, no spend
make e2e         # Playwright (Chromium fake mic): capture, gateway round trip, voice turn, widget, lab panel, WebRTC spike
uv run python harness/gate.py   # the CI latency/quality regression gate (fake time)
```

Run the pieces by hand: `go run ./cmd/gateway` (in `services/realtime-gateway`), `uv run python -m voicecore.server` (mock providers; `--providers live` for real ones), `pnpm --filter @voicecore/docs start` (docs site with the assistant, :3000), `pnpm --filter @voicecore/demo dev`.

The docs site ([`apps/docs`](apps/docs)) is the assistant's only source. It is a Docusaurus site about building, measuring and tuning voice agents, using this repository as the worked example. The assistant chats normally, but every fact it gives comes from a cited section. When it cites one, the page opens at that section and highlights it, without a reload, so the voice session continues.

### Live providers (spends money)

Copy `.env.example` to `.env` and fill in the keys, then `uv run python -m voicecore.server --providers live` (or `PROVIDERS=live docker compose up`).

- **Spending is guarded.** Every live session reserves its caps first (STT 300 s of speech, LLM $0.02, TTS 4,000 characters with Deepgram or 1,500 with Cartesia) in `benchmarks/spend_ledger.json`, and [`voicecore/budget.py`](services/agent-core/voicecore/budget.py) refuses anything over the project caps.
- **Keys stay on the server.** The browser only ever holds a single-use gateway token, valid for 60 s.

## Operations

Step 09 made the stack production-ready without hosting it. Everything below runs locally, with mock providers unless stated.

| Area | What there is | Start here |
|---|---|---|
| **Health and shutdown** | `/healthz` and `/readyz` on both services; SIGTERM drains open calls (the gateway up to 25 s), settles their spend, then exits 0 | [runbooks](docs/ops/runbooks.md) |
| **Monitoring** | `docker compose --profile monitoring up -d --build --wait`: Prometheus, Alertmanager, Loki, Grafana on :3001. Alert rules, one per target, each with a runbook; alerts go to a local sink | [monitoring](docs/ops/monitoring.md), [targets](docs/ops/slos.md) |
| **Resilience** | Circuit breakers per provider and per orchestrator; speech-to-text reconnects once; a 20 s limit on each answer; the widget reconnects to the same session | [ADR 0004](docs/adr/0004-deploy-abuse-resilience-scale.md) |
| **Abuse and spend** | Single-use, IP-bound tokens; Cloudflare Turnstile (off until a sitekey is set); per-IP daily quota; a public budget of $2 ($0.50 a day) inside the $5 cap, then text-only answers | [data map](docs/ops/data-map.md) |
| **Scale** | `docker compose --profile scale up`: two gateways and two orchestrators behind nginx, sharing a Redis ledger | [load report](reports/load.md) |
| **Deploy** | A Fly.io app, configured and tested locally, **not deployed** | [deploy guide](docs/ops/deploy.md) |
| **Incidents** | Severity levels, a template and two write-ups | [incidents](docs/ops/incidents.md) |

Checks: `make monitoring-check`, `make monitoring-test`, `make scale-test` and `make fly-image-test` (the last three need Docker).

## Repository map

| Path | What |
|---|---|
| [`packages/protocol/`](packages/protocol/SPEC.md) | wire protocol spec, golden vectors, TS codec |
| [`packages/web-sdk/`](packages/web-sdk/src) | capture (resampler, framer), `VoiceClient`, playout with generation fence, headless Node client |
| [`services/realtime-gateway/`](services/realtime-gateway) | Go gateway: sessions, resume, queues, counters, traces; `cmd/wsload`, `cmd/fakeorch` |
| [`services/agent-core/voicecore/`](services/agent-core/voicecore) | `turntaking/` (VAD, floor, echo gate), `runtime/` (generations), `providers/`, `answer/` (ingest, hybrid retrieval, grounding), `server.py` |
| [`apps/docs/`](apps/docs) | Docusaurus docs site: the assistant's corpus; `src/theme/Root.jsx` opens and highlights cited sections |
| [`apps/demo/`](apps/demo) | landing page, embeddable widget (`voicecore.js`), `?lab=1` timeline panel, Playwright suites |
| [`harness/`](harness) | fixture builders, runners (in-process fake time, WSS), timeline and metrics, benchmarks, evals, CI gate |
| [`experiments/`](experiments) | RTP jitter buffer and RFC 3550 jitter; Pion WebRTC spike |
| [`fixtures/`](fixtures) | LibriSpeech-derived audio (CC BY 4.0, [attribution](fixtures/audio/ATTRIBUTION.md)), uv docs snapshot (MIT/Apache-2.0), answer key, adversarial docs |
| [`docs/`](docs) | [architecture](docs/architecture.md), [portfolio story](docs/portfolio_story.md), [media internals](docs/media_internals.md), ADRs, step plans; [`docs/ops/`](docs/ops) runbooks, targets, incidents, deploy guide |
| [`monitoring/`](monitoring) | Prometheus rules and tests, Alertmanager routes, Loki, Alloy, Grafana dashboard |
| [`deploy/`](deploy) | Fly.io image and config (`deploy/fly`), the scale profile's nginx and test ledger (`deploy/scale`) |

## Status and open items

Steps 00–08 are done, and Step 09 (production readiness) is in its last phase. These items need a person or a decision:

- the dummynet (`sudo`) network-shaping runs;
- the manual acoustic barge-in and speaker/AEC checks;
- the 20-answer manual audit ([reports/answer_audit.md](reports/answer_audit.md));
- deploying the Fly app, with real Turnstile keys and rotated provider keys;
- the live load test (about $0.17, not yet approved).

[EXECUTION_STATUS.md](EXECUTION_STATUS.md) tracks every step with its evidence.

For coding agents: start with [MASTER_AGENT_GUIDE.md](MASTER_AGENT_GUIDE.md) and [CLAUDE.md](CLAUDE.md). The build plan is [docs/IMPLEMENTATION_PLAN.md](docs/IMPLEMENTATION_PLAN.md).
