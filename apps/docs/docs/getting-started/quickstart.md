---
title: Quickstart
description: Run VoiceCore on your machine with mock providers, run each process by hand, start this docs site with its voice assistant, and open the lab timeline.
---

## What you need before you start

For the Docker path you need Docker with Compose. Nothing else is required, and mock providers need no API keys.

To run the processes by hand, or to run this docs site, you need:

- Go 1.25 or newer, for the gateway;
- Node 24 with pnpm 11, for the demo app, the widget and this docs site;
- Python 3.12 with uv, for the orchestrator;
- ffmpeg, only if you rebuild the audio fixtures.

Install the dependencies once from the repository root:

```bash
uv sync && pnpm install
```

`uv sync` installs the orchestrator package (`services/agent-core`) into the workspace environment. `pnpm install` installs the browser SDK, the demo app and the docs site. After that, every command on this page runs from the repository root unless it says otherwise.

## Run the whole stack with docker compose

Docker Compose starts the orchestrator, the gateway, the demo app and this docs site, with mock providers by default:

```bash
docker compose up --build        # gateway :8080, orchestrator, demo :5173, docs :3000
open http://localhost:3000       # this docs site with the voice assistant
uv run python harness/smoke.py   # optional: one typed question, expects a cited answer
```

- The **docs site** is published on `127.0.0.1:3000`, with the widget in the corner.
- The **demo app** is published on `127.0.0.1:5173`, with the lab timeline at `/?lab=1`.
- The **gateway** is published on `127.0.0.1:8080`.
- The **orchestrator** listens on port 8765 inside the Compose network only. The gateway reaches it at `ws://agent-core:8765`.

The first build bakes the embedding model and the vectors of these pages into the orchestrator image, so it takes a few minutes, and later starts take seconds. Rebuild after you edit the docs. The smoke script gets a token, opens the WebSocket, asks one question by text and exits 0 when a cited answer arrives.

## What mock providers do and do not do

Mock mode is the default for both `docker compose up` and `python -m voicecore.server`. It spends nothing and needs no keys.

- The **mock speech-to-text** returns one canned transcript every time you pause, whatever you said.
- The **mock language model** streams one scripted answer with citations.
- The **mock text-to-speech** plays a 220 Hz tone, not speech. Hearing a tone means the audio path works.

Everything else is real: Silero voice activity detection, the turn-taking floor, the generation runtime, retrieval, the gateway and the browser playout. Mock mode always uses fixed 800 ms endpointing, because the mock STT returns its final at every pause and would end every turn early with the eager policy. For spoken answers grounded in these pages, use [live providers](live-providers.md).

## Run the gateway, orchestrator and demo by hand

Run each process in its own terminal. Start the orchestrator first: on startup it loads Silero VAD and builds the docs index, and the gateway dials it for every new session.

```bash
# terminal 1: orchestrator on ws://127.0.0.1:8765, mock providers
uv run python -m voicecore.server

# terminal 2: gateway on http://127.0.0.1:8080
cd services/realtime-gateway && go run ./cmd/gateway

# terminal 3: demo app on http://localhost:5173
pnpm --filter @voicecore/demo dev
```

The defaults line up. The orchestrator listens on `127.0.0.1:8765`. The gateway listens on `127.0.0.1:8080` and dials `ws://127.0.0.1:8765` (its `-upstream` flag). The demo points its widget at `http://localhost:8080`, or at `VITE_GATEWAY` when you set it. Embedding vectors are cached under `.cache` after the first build, so later orchestrator starts are faster.

## Run this docs site with its voice assistant

This site embeds the same widget. To talk to it, run the orchestrator and the gateway next to the docs site:

```bash
uv run python -m voicecore.server                         # orchestrator :8765
(cd services/realtime-gateway && go run ./cmd/gateway)    # gateway :8080
pnpm --filter @voicecore/docs start                       # docs site :3000
```

- `pnpm --filter @voicecore/docs start` builds the widget first and copies `voicecore.js` into the site's `static/embed/` folder, then serves the site on `http://localhost:3000`.
- The site points the widget at `VOICECORE_GATEWAY`, default `http://localhost:8080`.
- The gateway's default allowed origins, `localhost:*` and `127.0.0.1:*`, already include port 3000.
- The orchestrator indexes the folder given by `--docs-dir`, default `apps/docs/docs`. It builds citation links from `--docs-url`, default `http://localhost:3000/`.

With mock providers you hear a tone. Add `--providers live` to the orchestrator for spoken answers from these pages.

## Open the lab timeline

The demo app has a second view for one session's timing. Open `http://localhost:5173/?lab=1`.

The lab panel draws one session's merged trace:

- **stage bars** for endpoint wait, STT, LLM first token, TTS first audio and playout start;
- **speaking lanes** for the user and the agent, with interrupted generations marked;
- **events** from each process, which you can filter by process, and the gateway's drop and gap counters.

By default it loads a sample timeline from `/lab/sample-timeline.json`. Add `?trace=<url>` to load another one, or use the "Load trace" button to open a JSON file. You make timelines with `uv run python harness/session_timeline.py RUN_DIR`, which aligns the browser, gateway and orchestrator traces on one clock and writes `RUN_DIR/timelines/<session>.json`. Traces hold timings, not transcript or answer text, unless a run asks for text.

## Run the tests without keys or spend

The test suites run offline and spend nothing:

```bash
make test                        # Go (race + synctest), Python (pytest, fake time), TypeScript (vitest)
make e2e                         # Playwright with Chromium's fake microphone
uv run python harness/gate.py    # the CI latency and quality regression gate, on fake time
```

- `make test` covers the protocol vectors, the gateway, turn-taking, the runtime, providers with mocks, answers and the browser playout.
- `make e2e` checks capture, the gateway round trip, a voice turn, the widget and the lab panel in a real Chromium.
- `harness/gate.py` replays 12 dev turns, 3 interrupts and 2 echo-only clips in-process. It fails when a latency grows by more than 100 ms over the recorded measurement or a count gets worse.
