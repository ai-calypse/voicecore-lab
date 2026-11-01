---
title: Configuration reference
sidebar_label: Configuration
description: Every gateway and orchestrator command-line flag, the environment variables, docker compose usage and the budget caps that guard live provider spend.
---

This page lists every setting VoiceCore reads: the flags of the Go gateway (`services/realtime-gateway/cmd/gateway/main.go`), the flags of the Python orchestrator (`services/agent-core/voicecore/server.py`), environment variables, the `docker compose` setup and the spend caps for live providers. Defaults are the values in the code.

## Gateway command-line flags

Run the gateway with `go run ./cmd/gateway` from `services/realtime-gateway`, or the built binary. Go flags take one dash, as below. The defaults are safe for one developer on one machine: the gateway listens on loopback only and accepts browsers and Host headers from localhost. It takes these flags:

| Flag | Default | What it sets |
|---|---|---|
| `-addr` | `127.0.0.1:8080` | listen address for HTTP and the client WebSocket |
| `-upstream` | `ws://127.0.0.1:8765` | orchestrator base URL, or several separated by commas. Each new session goes to the orchestrator with the fewest of this gateway's sessions (ties take turns), skipping one that answers 503 or whose breaker is open, and stays there for life. It dials `<upstream>/v1/session/<session id>` |
| `-redis-url` | empty (this process's memory) | shared store for used token nonces and daily quotas, which several gateway copies need. If it is down, new sessions are refused (1013) and quotas are skipped with a warning |
| `-origins` | `localhost:*,127.0.0.1:*` | allowed browser origins for the WebSocket, comma separated |
| `-trace` | empty (off) | append trace events, as JSON lines, to this file |
| `-max-sessions-per-ip` | 4 | live sessions per client IP; 0 means no limit |
| `-max-sessions` | 50 | live sessions in total; 0 means no limit |
| `-tokens-per-minute` | 10 | `POST /v1/session` requests per client IP per minute; 0 means no limit |
| `-sessions-per-ip-per-day` | 0 (no limit) | session tokens per client IP per UTC day, counted only for requests that passed every other check; kept in memory, so a restart resets the count |
| `-hosts` | `localhost,127.0.0.1,::1` | allowed `Host` header names, comma separated; empty allows any |
| `-drain` | `25s` | on SIGTERM, how long open sessions may finish before they are ended with reason `shutdown` |
| `-probe` | empty | GET this URL and exit 0 on HTTP 200, else 1; the container healthcheck, since the image has no curl |
| `-turnstile-url` | Cloudflare's siteverify | where Turnstile tokens are checked; tests point it at a fake |
| `-admin-addr` | empty (off) | operator listener for `/metrics` (Prometheus) and `/debug/counters`; docker compose uses `0.0.0.0:9091` and publishes it on 127.0.0.1 only |
| `-env` | `dev` | `prod` refuses to start, listing every gap, unless `GATEWAY_SECRET` (32+ bytes), `TURNSTILE_SECRET` (or `-human-check off`), non-local `-origins` and `-hosts` without catch-all patterns, and `-trusted-proxies` are set |
| `-copy-id` | `gw` | this gateway copy's id; every session id is `s-<copy id>-<16 hex>`, so a load balancer can route a resume to its owner |
| `-trusted-proxies` | empty | comma-separated CIDRs, such as a load balancer's, whose `X-Forwarded-For` header is believed for the client IP; empty ignores the header |
| `-agents-dir` | empty | the console's published agent bundles, mounted read-only; a token request may then name an agent with a live version there, and `agents/_site/origins.json` adds the console's allowed websites to `-origins`, read again within a second of a change |
| `-widget` | empty (not served) | the built `voicecore.js`, served at `/widget.js`, so a site's snippet loads the widget from the gateway |
| `-console` | empty (not proxied) | the console's address, such as `http://127.0.0.1:8000`; every path the gateway does not serve goes there, with the client's address and scheme, so one host carries the voice server and its dashboard |
| `-human-check` | `on` | `off` lets `-env prod` start without `TURNSTILE_SECRET`, on purpose, with a warning; the rate limits and spend caps still apply |

The `-hosts` check refuses other host names with HTTP 421, which blocks DNS rebinding. The benchmark runner starts the gateway with `-max-sessions-per-ip 0 -tokens-per-minute 0`, because all its clients share one IP.

## Gateway limits that have no flag

Some gateway limits are fixed in `session.Defaults` (`services/realtime-gateway/session/server.go`) and have no command-line flag. They apply to every session the gateway serves. Change them in code if you need to:

| Setting | Value | Effect |
|---|---|---|
| Token lifetime | 60 s | a session token from `POST /v1/session` expires after this |
| Hello timeout | 5 s | the first WebSocket message must be `hello` within this time |
| Heartbeat | 10 s | no client message for this long closes with 4003 |
| Resume window | 10 s | a disconnected session can be resumed within this time |
| Upstream queue | 50 frames (1 s) | mic frames buffered towards the orchestrator |
| Client queue | 1,500 frames (30 s) | agent frames buffered towards the client |
| Session age | 15 minutes | a session ends with reason `expired` after this |
| Text length | 500 characters | longest `text.input` text; longer closes with 1008 |
| Queued events | 256 | client events waiting for the orchestrator; more closes with 1008 |

These values match the session rules in [Wire protocol](wire-protocol.md). The mic rate limit (real-time pace with a 2 s burst) and the `text.input` rate limit (1 per second, burst of 5) are also fixed in code.

## Orchestrator command-line flags

Run the orchestrator with `uv run python -m voicecore.server` from the repository root. With no flags it serves mock providers on `127.0.0.1:8765`, answers from this docs site and writes no traces. The gateway's `-upstream` flag must point at the address and port you choose here. It takes these flags:

| Flag | Default | What it sets |
|---|---|---|
| `--providers` | `mock` | `mock` (no keys, no spend), `mock-billed` (mock providers that reserve and settle small fixed amounts, for ledger tests), `free` (no paid provider: each typed question gets the closest docs section, as text) `live` (Deepgram, OpenRouter and the `--tts` provider; spends money), or `auto` (per session: live once both `DEEPGRAM_API_KEY` and `OPENROUTER_API_KEY` are set, in the dashboard's key file or the environment, else free; what `create-voicecore` installs run, so keys added in the dashboard turn voice on with no restart) |
| `--agents-dir` | none | the console's published agent bundles; the gateway's `X-VoiceCore-Agent` header picks one per session ([control plane](../architecture/control-plane.md)) |
| `--default-agent` | `on` | `off`: every session must name a published agent, and the `--docs-dir` corpus is not indexed at startup (a console install) |
| `--host` | `127.0.0.1` | listen address; the Docker image passes `0.0.0.0` |
| `--port` | 8765 | listen port for `ws://HOST:PORT/v1/session/{id}` |
| `--trace-dir` | none (off) | write one trace file per session, `<dir>/<session id>.jsonl` |
| `--docs-dir` | `apps/docs/docs` | the Docusaurus docs folder the assistant answers from |
| `--docs-url` | `http://localhost:3000/` | base URL of that docs site; citations link there |
| `--policy` | `eager` live, `fixed` mock | endpointing policy: `fixed`, `adaptive`, `asr_assisted` or `eager` |
| `--llm-model` | `openai/gpt-oss-120b` | OpenRouter model id |
| `--llm-provider` | `Cerebras` for the default model | OpenRouter provider to try first; `any` lets OpenRouter route |
| `--llm-reasoning` | `low` for the default model | reasoning effort; `none` omits it, for models without reasoning |
| `--tts` | `deepgram` | text-to-speech provider: `deepgram` (Aura-2, `usd` pool) or `cartesia` (sonic-3.6, `cartesia_credits` pool) |
| `--env` | `dev` | `prod` refuses to start unless the spend ledger is safe: in Redis, or on a mounted volume rather than the image's own filesystem, where a new machine would start again at 0 spent |
| `--pool` | `usd` | `public` makes every reservation also count against the public sub-cap; over it, sessions answer in text from the docs |
| `--drain-s` | 25 | on SIGTERM, seconds open sessions may finish before they are ended with reason `shutdown` |
| `--metrics-port` | 0 (off) | serve Prometheus `/metrics` on this port; docker compose uses 9464 and publishes it on 127.0.0.1 only |
| `--metrics-host` | `0.0.0.0` | listen address for `/metrics`, so a scraper inside compose can reach it |

On startup the orchestrator starts serving at once, then loads the Silero VAD model and the docs index in a background thread. Until they are loaded, `GET /readyz` answers 503 and a new session's WebSocket upgrade gets HTTP 503, so the first session never stalls. The `--llm-*` and `--tts` flags only matter with `--providers live`. Docker Compose passes no `--tts` flag, so the stack always uses Deepgram for speech.

## Choosing the endpointing policy

The `--policy` flag picks how the orchestrator decides that the user has finished speaking (ADR 0002). The values come from `Policy` in `turntaking/floor.py`:

- **`fixed`:** the turn ends after 800 ms of silence. This is the default with mock providers.
- **`adaptive`:** the silence depends on how long the user spoke: 400 ms after under 1 s of speech, 700 ms after 1 to 3 s, 1,000 ms after more than 3 s.
- **`asr_assisted`:** the turn ends on a punctuated final transcript after 300 ms of silence, otherwise on the adaptive silence.
- **`eager`:** the default with live providers. After 200 ms of silence the session asks the STT to finalize. A punctuated final after at least 200 ms of silence ends the turn; without one, the turn ends after 800 ms.

Do not use `eager` or `asr_assisted` with mock providers. The mock STT returns its canned final at every pause, so every turn would end early. The measured trade-offs between these policies are in [Tune latency](../guides/tune-latency.md).

## Pointing the assistant at a docs folder

Two orchestrator flags tell the answer engine what to answer from:

- `--docs-dir` is the folder of Markdown pages to index. The default is this docs site's `apps/docs/docs`, resolved from the repository root.
- `--docs-url` is the base URL of the site that serves those pages. The default is `http://localhost:3000/`, where `pnpm --filter @voicecore/docs start` and the compose `docs` service run the site.

At startup the orchestrator reads every `.md` file under `--docs-dir`, splits each page at its `##` and `###` headings, and builds a citation URL for each section: the base URL, the page route and the heading's anchor, the way Docusaurus renders them. Files whose name starts with `_` are skipped. Embedding vectors are cached under `.cache` after the first build.

If you serve the site somewhere else, set `--docs-url` to that address, or the citation links will point at localhost. How to write pages that cite well is in [Add your own docs](../guides/add-your-own-docs.md).

## Environment variables

VoiceCore reads the environment variables below. The three provider keys, `GATEWAY_SECRET` and `TURNSTILE_SECRET` are secret. None of them is needed for mock mode: with no variables set, the stack runs mock providers, the gateway makes a random token secret, and both web apps talk to the gateway on `http://localhost:8080`. The last three are read when the demo or this site is built or started with its dev server, not by the served pages.

| Variable | Read by | Meaning |
|---|---|---|
| `DEEPGRAM_API_KEY` | orchestrator | Deepgram key for speech-to-text and the default text-to-speech, live mode only |
| `OPENROUTER_API_KEY` | orchestrator | OpenRouter key, live mode only |
| `CARTESIA_API_KEY` | orchestrator | Cartesia key, only for `--tts cartesia` |
| `GATEWAY_SECRET` | gateway | fixed secret for session tokens; otherwise a random secret per gateway process |
| `TURNSTILE_SECRET` | gateway | Cloudflare Turnstile secret; when set, `POST /v1/session` needs a passed human check. Unset (the default) means no check. Cloudflare's test secret `1x0000000000000000000000000000000AA` always passes |
| `LOG_FORMAT` | gateway, orchestrator | `json` for one JSON object per log line (docker compose sets it); anything else, or unset, gives plain text |
| `VOICECORE_LEDGER` | orchestrator, harness | path of the spend ledger, default `benchmarks/spend_ledger.json`; or a `redis://` URL for a ledger shared by several orchestrators, which must first be seeded with `python -m voicecore.budget migrate` |
| `VOICECORE_VERSION` | orchestrator | the version `/healthz` reports; default `dev` |
| `PROVIDERS` | docker compose | `mock` (default) or `live`, passed to the orchestrator |
| `PUBLIC_GATEWAY` | docker compose build | the gateway URL baked into the demo and docs images, for the widget and the pages' `connect-src`; default `http://localhost:8080` |
| `HOST_UID`, `HOST_GID` | docker compose | user the orchestrator container runs as; default 10001 |
| `VITE_GATEWAY` | demo app build | gateway URL for the demo page's widget; default `http://localhost:8080` |
| `VOICECORE_GATEWAY` | docs site build | gateway URL for this site's widget; default `http://localhost:8080` |
| `DOCS_URL` | docs site build | the site's public URL; default `http://localhost:3000` |
| `VOICECORE_CAP_USD` | orchestrator, console | the install's total cap in US dollars; default 5 (`create-voicecore` writes 10) |
| `VOICECORE_PUBLIC_TOTAL`, `VOICECORE_PUBLIC_DAILY` | orchestrator, console | the public sub-cap in total and per UTC day; defaults 2 and 0.50 (`create-voicecore` writes 10 and 1) |
| `VOICECORE_LIMITS_FILE` | orchestrator, console | the spending limits set on the dashboard's Voice page (`limits.json`: `daily_usd`, `total_usd`): the console writes it, the orchestrator reads it at each reservation. When set, its total replaces `VOICECORE_PUBLIC_TOTAL` (and raises `VOICECORE_CAP_USD` when higher), and its daily limit `VOICECORE_PUBLIC_DAILY` |
| `VOICECORE_VECTORS_DIR` | orchestrator, console | where computed vectors are cached when the image's own cache is read-only |
| `VOICECORE_KEYS_FILE` | orchestrator, console | the provider keys set on the dashboard's Voice page (`keys.json`, mode 600): the console writes it, the orchestrator reads it at each new session, ahead of the environment |
| `CONSOLE_ADMIN_PASSWORD` | console | the admin's password, at least 12 characters; taken at start, and a changed one signs everyone out. `create-voicecore` generates it and `create-voicecore info` shows it ([install](../getting-started/install.md)) |
| `CONSOLE_SETUP_TOKEN`, `PUBLIC_VOICE_URL`, `VOICECORE_PROVIDERS`, `CONSOLE_STATIC`, `TURNSTILE_SITEKEY` | console | a first-run setup token (instead of `CONSOLE_ADMIN_PASSWORD`), the voice server's public address for the snippet, the provider mode for the banner, the built UI folder, and the sitekey added to the snippet |

`.env.example` lists the four that a live setup can use. `CARTESIA_API_KEY` is only needed with `--tts cartesia`. Copy it to `.env` (it is gitignored) and fill in the keys.

## Where API keys are read from

The orchestrator reads each provider key with `voicecore.keys.key(name)`:

1. the environment variable of that name, if it is set and not empty;
2. otherwise the line `NAME=value` in the repository's `.env` file.

Keys never leave the server. The browser only ever gets a 60 s gateway session token, and the orchestrator talks to the providers itself. Mock mode needs no keys at all, so an empty `.env`, or none, is fine for mock runs.

In Docker, compose loads `.env` into the orchestrator container if the file exists (`required: false`), and passes only `GATEWAY_SECRET` to the gateway. The rule in `keys.py` is that keys are never logged.

## Log lines

Both services write one line per event: the gateway to stderr, the orchestrator to stdout. With `LOG_FORMAT=json`, each line is a JSON object with `ts`, `level`, `logger` (orchestrator only) and `msg`, plus only these fields when they apply: `session_id`, `gen`, `kind`, `reason`, `provider` and `duration_ms`, and `exc` with the traceback when an exception is logged. The orchestrator's formatter drops every other field, so a transcript passed by mistake never reaches a log. It also replaces the loaded provider key values, and anything shaped like an OpenRouter or Cartesia key or a `Token` header value, with `[redacted]`.

Each session logs `session started` and `session ended`; the gateway's end line has the `reason`, and both have `duration_ms`. A provider failure logs `provider error` with `provider` (`stt`, `llm` or `tts`) and `kind` (`retryable`, `rate_limited` or `fatal`). A bug in VoiceCore's own answer code logs `answer failed` with its traceback instead, so it is never counted as a provider failure. A malformed client message logs `protocol error` with only the exception type as `kind`, because the message text could echo what the client sent. Logs never contain transcripts, answers, audio, keys, tokens or the resume key. To follow one session, filter on its `session_id`.

## Run the stack with docker compose

`docker-compose.yml` runs four services: `agent-core` (the orchestrator), `gateway`, `demo` and `docs`. Mock providers are the default, so it needs no keys and spends nothing:

- `agent-core` is built from `services/agent-core/Dockerfile` and listens on 8765 inside the compose network only. Its Prometheus `/metrics` is published on `127.0.0.1:9464`.
- `gateway` is built from `services/realtime-gateway`, published on `127.0.0.1:8080`, and dials `ws://agent-core:8765`. Its admin listener, `/metrics` and `/debug/counters`, is on `127.0.0.1:9091`.
- `demo` is published on `127.0.0.1:5173`: the demo page and the lab timeline at `/?lab=1`.
- `docs` is published on `127.0.0.1:3000`: this docs site with the voice assistant.

```bash
docker compose up --build                 # mock providers: no keys, no spend
PROVIDERS=live docker compose up          # live providers, keys from .env
docker compose --profile monitoring up --build --wait   # adds Prometheus, Alertmanager, Loki, Alloy and Grafana
docker compose --profile scale up -d --build --wait redis seed orch-1 orch-2 gw-1 gw-2 lb   # two of each, behind nginx on :8090
HOST_UID=$(id -u) HOST_GID=$(id -g) PROVIDERS=live docker compose up   # Linux
```

Both web images send security headers from nginx: a Content Security Policy, `X-Content-Type-Options: nosniff` and `Referrer-Policy: strict-origin-when-cross-origin`. The policy allows scripts only from the site itself, from Cloudflare Turnstile and by the hashes of the few inline scripts Docusaurus writes. `scripts/csp.mjs` computes the hashes at build time. Network connections are allowed to the site and to the gateway in `PUBLIC_GATEWAY`. The pages cannot be framed (`frame-ancestors 'none'`).

The `scale` profile runs two gateways and two orchestrators behind nginx on `127.0.0.1:8090`, sharing one Redis for the budget ledger, token nonces and daily quotas. A one-shot `seed` service copies the file ledger's totals into Redis before the orchestrators start, so the caps never restart at zero. nginx sends a reconnect (`/v1/ws?resume=s-gw1-…`) to the gateway that owns the session, and everything else round robin. It uses billed mocks: no provider is called. Measurements are in `reports/load.md`.

The `monitoring` profile adds Prometheus (`127.0.0.1:9090`), Alertmanager (`127.0.0.1:9093`), an alert sink that prints each alert as a log line (`docker compose logs alert-sink`), Loki with 7-day log retention, Alloy to ship the containers' logs, and Grafana with the VoiceCore dashboard (`127.0.0.1:3001`). All ports bind to 127.0.0.1 only. The orchestrator image bakes in the embedding model and the docs vectors for `apps/docs/docs`, so it starts in seconds but the first build takes a few minutes. Live mode writes the shared ledger in `./benchmarks`, mounted into the container; on Linux, run the container as your own user so it can write there.

## Budget caps for live providers

Every paid provider call is covered by a reservation in the spend ledger, `benchmarks/spend_ledger.json`, before it runs. The live adapters cannot even be built without one (`providers/factory.py`). A reservation is written to the ledger at once, so a crash before settling still counts the worst case against the cap.

| Pool | Project cap | Covers | Reserved per session |
|---|---:|---|---|
| `usd` | $5.00 (`VOICECORE_CAP_USD` on an install) | Deepgram STT and TTS, OpenRouter | STT: 300 s of audio × $0.0077 per minute = $0.0385; LLM: $0.02; TTS with `--tts deepgram`: 4,000 characters × $0.030 per 1,000 = $0.12, reserved when the session first speaks |
| `cartesia_credits` | 16,000 credits | Cartesia, 1 credit per character | TTS with `--tts cartesia`: 1,500 characters, reserved when the session first speaks |
| `public` (inside `usd`) | $2.00 in total, $0.50 per UTC day | sessions of an orchestrator started with `--pool public` | the same reservations, counted against both `usd` and `public` |

A public deployment runs the orchestrator with `--pool public`. When a session would pass the public total or today's share, it is not refused. The assistant says "Today's voice demo budget is used up. I can still point you to the right page: ask a question by typing." It ignores the microphone, and answers each typed question with the closest docs section and a link to it, with no paid call at all. The `usd` cap of $5.00 still holds over everything. Reservations count in full until their session settles, so the daily share is conservative. About two sessions can be open at once on $0.50 before new visitors get the text answers, even when actual spend is only cents. The public sub-cap counts dollars only: a Cartesia session's credits never count against it.

When a session ends, each reservation is settled to the amount actually used. The caps are a user decision from 2026-10-29: $5 for the whole project, and 16,000 of the 20,000 Cartesia credits owned. Benchmark scripts reserve from the same pools, for example $0.05 for one `llm_ttft.py` run.

## What happens when a budget cap is reached

Each cap fails in a way that keeps the session useful where it can:

- **Project cap at session start:** if the STT or LLM reservation would pass the `usd` cap, the orchestrator refuses the session. It sends `session.ended` with reason `budget` and closes.
- **Per-session STT cap, 300 s of audio:** the STT reports a fatal error. The agent says "Voice input has reached its limit for this session. You can keep typing your questions." Text questions still work. Only speech is sent to the STT (with 300 ms before and 600 ms after it), so silence does not use up the cap.
- **Per-session LLM cap, $0.02:** before each call the adapter checks the cost so far plus this prompt with worst-case output. Past the cap, the call fails as fatal, and the agent says it is having trouble answering.
- **Per-session TTS cap, 4,000 characters with Deepgram or 1,500 with Cartesia:** if the TTS reservation is refused, or the cap is reached, TTS fails as fatal. The agent says once, as a text reply, "Spoken replies have reached their limit for this session, so I'll answer in text. Close and reopen me to talk again." Later answers arrive as text, unless one still fits in the characters left. Reopening the assistant starts a new session with fresh caps.
