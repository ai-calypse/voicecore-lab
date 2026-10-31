# Step 10: VoiceCore Platform — self-hosted console, one-command install, 10-minute integration

**Status:** approved by the owner 2026-10-31. Executed through [step_10_voicecore_platform.md](step_10_voicecore_platform.md), which holds the task ids and registers.

## Context

VoiceCore runs live, but integrating it today means cloning the repo, swapping in your own docs folder, setting flags and editing a deploy. The owner wants any company to integrate it as simply as ElevenLabs Agents:
- a visual console to create agents and give them docs;
- a "test agent" button;
- an embed snippet to copy;
- a one-command install;
- live in about 10 minutes.

The work should show senior-level architecture: SOLID, a control-plane/data-plane split, TDD.

**Owner decisions (2026-10-31):**
- **Platform:** a self-hosted console, one organisation per install. No sign-up, billing or tenant isolation.
- **Docs sources (v1):** file upload (Markdown, zip, plain text), a Git repository, pasted text.
- **Install:** `npx create-voicecore`.
- **Publishing:** npm (`create-voicecore`; the name is free, `npm view` returns 404) and GHCR images.
- **Console sign-in:** one admin, created on first run, plus API keys.
- **Public demo:** read-only, on the existing Fly setup.

**What exists today (surveyed):**
- One "agent" per orchestrator process. The docs index is built at startup (`server.py:368-378`), and the name is hard-coded as `name="VoiceCore"` (`:203`).
- No agent id anywhere: not in the token, `hello`, the upstream dial (`server.go:577`), metrics or logs.
- The token is `exp.nonce.HMAC(ip)` (`server.go:339-352`). Allowed origins are global (`serveWS` `:401`).
- `Request.path` includes the query string, so `?agent=` would corrupt the sid parse at `server.py:216`.
- Each `Index` loads its own embedding model (`index.py:45-53`). There is no way to load an index from a file.
- `CAPS={"usd":5.00}` is hard-coded (`budget.py:17`), so any self-hosted live install would stop for good at $5.
- The Deepgram voice is fixed when the module is imported (`deepgram_tts.py:25-26`).
- No install script exists, and no images are published. The first compose build takes minutes.

**Rules this step must amend first** (`MASTER_AGENT_GUIDE.md:78`, `docs/README.md:41`):
- master plan non-goals (`voicecore_lab_career_aligned_plan.md:149`): "complex admin UI", "private org knowledge sources";
- `MASTER_AGENT_GUIDE.md:11`: "tenant admin, account management… oversized product UI";
- ADR 0001 `:41`.

The new wording: *"A self-hosted, single-organisation console that indexes the organisation's own docs on its own hardware is in scope (ADR 0005). Still out: SaaS plans, billing, tenant isolation, user accounts beyond one admin, and knowledge hosted by this project."*

**Done means:**
1. On a clean machine with Docker, `npx create-voicecore` installs everything.
2. In the console: set up the admin → create an agent → upload docs → Publish → ask a question in the preview and get a cited answer → copy one `<script>` tag → paste it on a page → the widget answers there.
3. The whole flow takes under 10 minutes, measured in CI.
4. Voice keeps working with the console stopped.
5. The read-only demo is live at `voicecore-docs.fly.dev/console/`.

## Architecture

**Control plane / data plane.**
- The new **console** (FastAPI + React) owns agents, sources, builds and API keys.
- It **publishes** immutable, content-addressed **agent bundles** to a shared `agents` volume.
- The data plane (gateway + orchestrator) only reads that volume and never calls the console. So voice keeps working with the console stopped.

**Bundle format v1** (`voicecore/agents.py` is the only owner of the format; the console imports it):
- Layout: `agents/<id>/<ver>/{config.json, passages.jsonl, vectors.npy}` plus the pointer file `agents/<id>/current`.
- `ver = sha256(config + corpus)[:12]`, so the same content gives the same version and a settings-only publish needs no re-embedding.
- Publishing is atomic: write a temp folder → rename it → `os.replace` the pointer. The last 5 versions are kept.
- `config.json`: `format:1, name, docs_url?, instructions, first_message?, voice, llm, keyterms`.
- `voice` must be in `deepgram_tts.VOICES`; `llm` must be one of the keys of `openai_compat_llm.PRICES`, so cost estimates stay correct.

**How the agent id travels:**
1. Widget `data-agent="acme-docs"` → `POST /v1/session` form field `agent`.
2. The gateway checks the id against `^[a-z0-9][a-z0-9-]{0,39}$`; if `agents/<id>/current` is missing it answers 404 `unknown agent`.
3. A new `TokenFor(ip, agent)` signs a 4-part token `exp.nonce.agent.HMAC`. With no agent, the token keeps today's 3 parts byte for byte, so the existing deploy and tests don't change.
4. `hello` is unchanged.
5. The upstream dial adds the header `X-VoiceCore-Agent`.
6. The orchestrator resolves the agent **before** it reserves budget.
7. With no agent, it uses the default agent built from `--docs-dir`, as today.

**Hot reload without a watcher.** Each new session reads `current`, and `@lru_cache(16) load(root, id, ver)` loads that version. Open sessions keep the bundle they started with.

**One embedder per process.** A module-level `@functools.cache embedder()` is shared by every `Index`. Vectors cost about 1.5 KB per passage.

**Per-agent settings applied in `serve_session`** (`server.py:223-256`):
- `name`;
- operator `instructions`, appended *after* the grounding rules (they can't remove them);
- `first_message`, via a new `Session(greeting=)` that generalizes the `BUDGET_TEXT_ONLY` reply (`session.py:131`);
- `voice`, via `deepgram_tts.url_for()` into **both** `DeepgramTTS(url=)` and `open_socket(url=)`;
- `keyterms`, via `deepgram_stt.url_for()`;
- `llm`, via `llm_opts`;
- the `agent` label on logs (allowlist), traces and `sessions_total`.

**New `--providers free`.** Text answers from the customer's *own* docs, using the existing extractive `closest_section` path, with no voice and $0. Mock mode always gives the canned endpointing answer, which would confuse someone who uploaded their own docs.

**Spend caps from env** (`VOICECORE_CAP_USD`, `VOICECORE_PUBLIC_DAILY`, …), with today's numbers as defaults.

**Gateway serves the widget.** A `-widget` file flag serves `GET /widget.js`, built in a Node stage of the gateway Dockerfile. `go test` doesn't need it, and Fly is unchanged. The widget's endpoint defaults to **the script's own origin**, so the embed is one tag:
`<script src="https://voice.acme.com/widget.js" data-agent="acme-docs" async></script>`

**Console** (`services/console`, uv workspace member; FastAPI + uvicorn only in that member; pydantic and httpx already come in via `openai`):
- One `Store` (stdlib `sqlite3`, no ORM).
- Sources: a dict of fetcher functions, `{"upload","text","git"}`.
- Builds: `ThreadPoolExecutor(1)` plus a `builds` table. At startup, `running` rows become `failed: interrupted by restart`.
- One composition root, `create_app(data_dir, agents_dir, setup_token, now, run_git)`. Tests inject only real edges: the clock, git, folder paths.
- Uploads arrive as a raw body (`PUT …/sources/upload`), streamed with a size cap, so no `python-multipart`.
- `/api/docs` (OpenAPI) is the API reference.

**Console UI** (`apps/console`, Vite + React + TS; React is already in the lockfile via Docusaurus): no router library (a `location.hash` switch), no UI kit, native `<dialog>`, `<form>` and `<input type=file>`. Pages:
- Setup, Login, Agents.
- Agent:
  - **Knowledge:** dropzone, paste text, Git form, build status and log;
  - **Settings:** name, first message, instructions, voice, LLM, docs URL;
  - **Test:** an iframe of `/preview/<id>`, about 10 lines of HTML with the *real* snippet, so the test exercises exactly what users paste;
  - **Embed:** the snippet with a copy button, plus one sentence each for React/Next and Docusaurus;
  - a one-line "spent today / cap".
- API keys.

**Auth:**
- Passwords: `hashlib.scrypt` (n=2^14, r=8, p=1), at least 12 characters.
- Session cookie: HttpOnly, SameSite=Strict, Secure on https, stored in a sessions table.
- Every request that isn't GET: `Origin` check plus a JSON content type.
- Login: 5 attempts per minute per IP.
- Setup token: one-time, in the URL **fragment** (never logged), compared in constant time.
- API keys: `vck_` + 32 random bytes, stored as sha256, shown once.
- Recovery: `python -m voicecore_console reset-admin`.

**Least privilege:**
- The `console` volume: the console reads and writes.
- The `agents` volume: the console writes; the gateway and orchestrator mount it **read-only**.
- The ledger: the orchestrator writes; the console reads it only for the spend line.
- Provider keys: in the orchestrator's environment only.
- The console runs with `cpus: 1.0`, so embedding builds can't starve the real-time audio loop.

**Images: two, multi-arch, on GHCR:**
- `voicecore`: Python; runs the orchestrator *or* the console, chosen by `command:`.
- `voicecore-gateway`: Go plus `widget.js`.
- The CLI version equals the image tag.

**`npx create-voicecore`** (`packages/create-voicecore`: zero dependencies, plain `.mjs`, `node>=20`):
1. Checks Docker and Compose. If either is missing, it prints a specific message and the install link.
2. Asks for a folder and a mode:
   - **free:** $0, no keys;
   - **live:** asks for the Deepgram and OpenRouter keys (masked; written only to `.env`, mode 600) and the spend caps;
   - **public:** asks for a domain, runs a Caddy profile with automatic HTTPS (microphones need HTTPS), routes by path on one hostname (`/v1/*` and `/widget.js` to the gateway, everything else to the console), and asks for Turnstile keys or an explicit `-human-check off`, which `ValidateProd` accepts with a warning.
3. Generates `GATEWAY_SECRET` and a setup token.
4. Picks free ports.
5. Writes `compose.yml` with pinned image tags.
6. Runs `docker compose up -d --wait` and prints `http://localhost:8000/#/setup?token=…`.

`--yes --mode free` runs it with no questions, for CI.

**Read-only public demo, $0 extra.** A static console build (`VITE_DEMO=1`, base `/console/`) reads committed JSON snapshots, regenerated by a pytest through `TestClient` so they can't drift from the API. It is served by the **existing** `voicecore-docs` nginx. Its Test tab uses the existing default agent on `voicecore.fly.dev`, whose `ORIGINS` already include `voicecore-docs.fly.dev`. So there is no new Fly app and no public backend to attack.

**SOLID mapping:**
- **S:** `agents.py` = the bundle format; `sources.py` = untrusted input; `auth.py` = credentials; `publish.py` = build and publish; `app.py` = HTTP only; the gateway only checks that the pointer exists.
- **O:** new source kinds and catalog entries are data or one function; use cases don't change.
- **L:** the default agent (from `--docs-dir`) and a bundle agent are the same `Agent` type; a parity test proves it.
- **I:** the data plane depends only on the file layout; the gateway needs only "does this id exist".
- **D:** one composition root; edges (clock, git, paths, providers) are injected; nothing else is abstracted without a second implementation.

**Added by the review (see the Review record):**
- **Allowed websites without a restart.** The company's own site has to pass the gateway's Origin checks, both at `POST /v1/session` and at `websocket.Accept` (`server.go:226`, `:401`), and those read the global `-origins`.
  - The console gets a "Websites allowed to embed" setting for the install and publishes it to `agents/_site/origins.json`.
  - The gateway re-reads that file when its mtime changes, at most once a second, and adds it to `-origins` for both checks.
  - The installer asks "Which website will you embed it on?" (optional). Without this, the first real embed gets a 403 and the user has to edit `.env` and restart.
- **No default agent on customer installs.** The installer's compose runs `--default-agent off`, so the VoiceCore docs agent isn't there to confuse anyone and no corpus is indexed at startup. The Fly deploy keeps the default agent.
- **Installer lifecycle commands**, all in the same package:
  - `npx create-voicecore@latest upgrade` keeps `.env`, the secrets and the volumes, bumps the image tags, runs `compose pull && up -d --wait`, and the console migrates its database on start;
  - `npx create-voicecore keys` adds or rotates provider keys and switches free → live, restarting only the orchestrator;
  - `npx create-voicecore uninstall` runs `compose down`, and `--delete-data` adds `-v`.
  - Re-running the installer in an existing folder never overwrites secrets.
- **Reading the ledger safely.** The ledger is rewritten in place under `LOCK_EX` (`budget.py:77-93`), and a read-only mount can't open it `O_RDWR`. New `budget.read_totals(path)`: `O_RDONLY` with `LOCK_SH`. The console uses only this.
- **Schema and format versions.**
  - Console SQLite runs in WAL mode with `busy_timeout=5000`, one connection per request, and migrations through `PRAGMA user_version`.
  - The bundle reader rejects `format > 1` with "bundle format 2 needs a newer voicecore image".
  - Upgrade order: data plane images first, then the console (one `upgrade` command does this).
- **Image size budget.**
  - The Python image is about 1.03 GB uncompressed today (local `voicecore_lab-orch-2`); onnxruntime, fastembed, the model and the venv dominate.
  - Target: **450 MB or less compressed**, enforced by a CI check. Slimming: multi-stage build, no uv cache, only the quantized model.
  - The 10-minute claim is published with its bandwidth assumption.
- **Demo preview.** The docs nginx sends `frame-ancestors 'none'` (`scripts/csp.mjs:30`), so the demo's Test tab embeds the real widget script inline (no iframe), pointed at `voicecore.fly.dev`. The self-hosted console serves `/preview/<id>` with `frame-ancestors 'self'`.
- **Docker checks.** `docker info` must succeed (Docker installed *and running*), and `docker compose version` must be 2.20 or later (needed for `--wait`), each with its own message.
- **Free-mode upsell.** The console shows "Voice is off. Add provider keys: `npx create-voicecore keys`" while `PROVIDERS=free`. The installer recommends live when the keys are at hand.

**Deferred** (with triggers):
- Per-agent origins or caps: when two agents need different limits. The check would go at hello, against the token's agent, using a flat list of sub-caps.
- Usage page: when one line isn't enough; Grafana already exists.
- `.mdx` support: on first request.
- URL crawler.
- A `voicecore` agents CLI: when curl plus an API key isn't enough.
- Rollback UI: the pointer already supports it.
- S3 bundle store, for several hosts.

## Phases (TDD: RED literal test → GREEN least code; same rules as `docs/IMPLEMENTATION_PLAN.md` §A)

Order: P0 → P1 → {P2, P3, P4} → P5 → P5b → P6 → P8 → P9. P7 (Git) can come any time after P5 and is the first to slip. About 87 h in total.

| Phase | Hours | Key RED tests (literal expected values) | GREEN |
|---|---:|---|---|
| **P0 Scope and records** | 3 | links resolve; anchor check passes | Amend the master plan, the guide line 11 and ADR 0001 with the wording above. Write `docs/adr/0005-voicecore-platform.md`, `docs/step_10_voicecore_platform.md` (S10-T01…T10, registers) and `docs/PLATFORM_PLAN.md` (this plan). Add EXECUTION_STATUS rows. Fix the guide's stale "256 h / nine steps" (`:43`). |
| **P1 Answer-engine prerequisites** (seams 6, 21) | 4 | `test_index_accepts_vectors`: `Index(p2, vectors=np.ones((2,384),np.float32)).vectors.shape == (2,384)` and no cache file written. `test_indexes_share_one_embedder` (`a._embedder() is b._embedder()`). `test_bundle_golden_read`: `fixtures/agents/acme-docs/` gives `name == "Acme Docs"` and 3 passages. `test_publish_same_content_same_version`. `test_prune_keeps_five` | `Index(vectors=)`; module-level embedder; `VOICECORE_VECTORS_DIR`, writable and separate from the root-owned `/app/.cache`; `voicecore/agents.py` (read, write, publish, prune, current) |
| **P2 Orchestrator per agent** (seams 4, 14, 17) | 8 | `test_agent_header_selects_bundle` (free) → `"Closest section: Refunds > How refunds work."`. `test_unknown_agent_ends_unavailable` → `session.ended{reason:"unavailable"}` and `budget.total("usd") == 0.0`. `test_next_session_sees_new_version` (A cites v1, B cites v2). `test_free_mode_greets_then_answers` → `"Text answers from your docs. Voice turns on once provider keys are set."`. `test_first_message_is_first_reply` → `"Hi, I'm the Acme assistant."`. `test_operator_notes_follow_grounding` (`system.endswith("Operator notes: Answer in British English.")`). `test_tts_url_for_voice` → `"wss://api.deepgram.com/v1/speak?model=aura-2-orion-en&encoding=linear16&sample_rate=24000"`. `test_bundle_rejects_unknown_llm` → `ValueError("llm not in catalog: openai/gpt-5")`. `test_log_keeps_agent_field`. `test_default_and_bundle_agent_parity` | `--agents-dir`, `--providers free`, `Session(greeting=)`, `url_for` helpers, header parsing, labels |
| **P3 Gateway and widget** (seams 2, 13, 19) | 6 | Go: `TestTokenForAgent` (4 parts, `parts[2]=="acme-docs"`); `TestNoAgentTokenUnchanged` (3 parts); `TestUnknownAgent404` → `"unknown agent\n"`; `TestBadAgentID400` (`../x`) → `"bad agent id\n"`; `TestAgentHeaderUpstream` (fakeorch records `X-VoiceCore-Agent: acme-docs`, none for 3 parts); `TestTamperedAgentToken` → 4001; `TestWidgetJS` (200, `Cache-Control: public, max-age=300`). Playwright `widget.spec.ts`: body `agent=acme-docs`; endpoint defaults to the script's origin; a source with no URL renders no `<a>` | `TokenFor`, `useToken` returns the agent, `DialOptions.HTTPHeader`, `-agents-dir`/`-widget` flags, fakeorch records headers, Node stage in the gateway Dockerfile, SPEC.md §4 (event vectors unchanged) |
| **P4 Console core and auth** (seam 22) | 8 | `test_setup_needs_token` (403 without or with a wrong token; 201 with the right one; cookie `HttpOnly`, `SameSite=strict`); `test_setup_once` → 409 `"already set up"`; `test_password_min_12` → 422; `test_login_rate_limit` (6th → 429); `test_cross_origin_post_403` → `"cross-origin request"`; `test_api_key_once_hashed` (`vck_`, never listed, sha256 stored); `test_revoked_key_401`; `test_reset_admin_prints_fragment_url` (`"/#/setup?token="`) | `voicecore_console/{app,store,auth,__main__}.py` |
| **P5 Agents, sources, publish** (seams 21, 22) | 12 | `test_create_agent_slug` (`acme-docs`, then `acme-docs-2`; defaults `aura-2-thalia-en`, `openai/gpt-oss-120b`); `test_settings_rejects` (`voice:"robot"` → 422; `docs_url:"javascript:alert(1)"` → 422); `test_upload_zip` → `{"files":2,"skipped":["logo.png"]}`; `test_zip_slip` → 400 `"unsafe path in archive: ../evil.md"`; `test_zip_bomb` → 413 `"archive expands past 50 MB"`; `test_body_over_20mb` → 413; `test_paste_text` (page starts `"# Refunds\n"`); `test_publish_end_to_end` (build `done`, `current` = version, 3 passages); `test_flagged_sections_logged` → `"1 section skipped: it reads like instructions to the assistant"` (reuses `SUSPICIOUS`, `ingest.py:24`); `test_interrupted_build_failed_on_start`; `test_disable_removes_pointer`; `test_no_docs_url_blank_urls`; `test_passage_cap` (5,000) | `sources.py` (upload, text), `publish.py` |
| **P6 Console UI** (seam 23) | 14 | Playwright `console.spec.ts` "first run to cited answer": setup → create → upload `fixtures/agents/acme.zip` → Publish → "Live" → Test tab: typing "how do refunds work" shows `"Closest section: Refunds > How refunds work."` within 30 s. Embed snippet equals `<script src="http://127.0.0.1:18082/widget.js" data-agent="acme-docs" async></script>`. `/#/agents` with no session → `/#/login`. A rejected upload shows its reason. Each agent page shows a 4-step checklist (Add docs → Publish → Test → Embed), and each step is ticked once it is done. A build shows "Embedding 120 of 342 sections" while it runs. Free mode shows the "Voice is off" banner. Every form control has a label (axe check: 0 violations) | `apps/console` pages, `/preview/<id>` (with `frame-ancestors 'self'`), empty states, demo banner ("Read-only demo. Install it to try: `npx create-voicecore`"), disabled controls with a reason. Skills: `ui-taste` and `design-review` screenshots in both themes and at 375 px |
| **P7 Git source** (seam 22) | 5 | `test_git_url_rules` (`"only https URLs: http://github.com/a/b"`, `"host not allowed: 10.0.0.1"`); `test_sparse_clone_only_folder` (a local repo gives `["docs/a.md"]`); `test_symlink_skipped`; `test_size_cap` → `"folder larger than 20 MB"`; `test_resync_replaces_files` | Reuse `ingest.check_url` with `allowed=None`, meaning public addresses only. Hardened clone: `-c protocol.allow=never -c protocol.https.allow=always -c http.followRedirects=false -c core.symlinks=false clone --depth 1 --filter=blob:none --sparse --single-branch --no-tags`, env `GIT_TERMINAL_PROMPT=0 GIT_LFS_SKIP_SMUDGE=1 GIT_CONFIG_NOSYSTEM=1 HOME=<tmp>`, 60 s timeout |
| **P5b Review additions: origins, ledger, migrations** (seams 2, 10, 22) | 5 | Go `TestOriginsFileReload`: POST from `https://acme.com` → 403; write `{"origins":["acme.com"]}` → 200 within 1 s. `TestWSAcceptUsesReloadedOrigins`. Py `test_read_totals_shared_lock` (a writer process and a reader thread for 2 s never raise; totals are monotonic). `test_migrations_from_v1` (`PRAGMA user_version` 1 → current; agents kept). `test_bundle_format_too_new` → `"bundle format 2 needs a newer voicecore image"`. `test_default_agent_off` (no `X-VoiceCore-Agent` → `session.ended{reason:"unavailable"}`) | `origins.json` publish and gateway reload; `budget.read_totals`; `store.migrate()`; format guard; `--default-agent off` |
| **P8 Images, installer, caps, Caddy** (seams 10, 15, 19, 24) | 12 | `test_caps_from_env` (`VOICECORE_CAP_USD=20` → `"20.0"`, unset → `"5.0"`); `test_daily_cap_from_env` → `"1.0"`; Go `TestValidateProdHumanCheckOff` (the error doesn't mention `TURNSTILE_SECRET`); vitest: `renderEnv({mode:"free"})` contains `PROVIDERS=free` and a secret matching `/^[0-9a-f]{64}$/`; `.env` mode `0o600`; `--yes --mode free` with a docker shim records `compose up -d --wait`; no docker → exit 1 + `"Docker is not installed. Get it at https://docs.docker.com/get-docker/"`; port 8080 busy → `VOICE_PORT=8081`; `compose config --quiet` with and without `--profile public`; `check-mock-only` accepts `"free"`; Docker installed but not running → `"Docker is installed but not running. Start Docker Desktop and run this again."`; compose 2.19 → `"Docker Compose 2.20 or newer is needed (found 2.19.0)."`; a re-run in an existing folder keeps `GATEWAY_SECRET` byte for byte; `upgrade` rewrites only the image tags; `keys --deepgram … --openrouter …` sets `PROVIDERS=live` and restarts only `orchestrator`; `uninstall` without `--delete-data` never passes `-v`. Docker: `test_image_size_budget` (compressed `voicecore` image ≤ 450 MB) | `packages/create-voicecore/{index.mjs,template/compose.yml,template/Caddyfile}`; Dockerfiles (two images); `budget.py` caps from env |
| **P9 Release, timed install, demo, docs** (seam 25) | 10 | `test_install_to_cited_answer_under_10_min` (docker): `elapsed_s < 600` plus the literal answer, then `docker compose stop console`, and the answer still arrives. `test_demo_snapshot_matches_api`. Docs Playwright: `/console/` shows `"Read-only demo"` and `"VoiceCore docs"`. `test_api_reference_lists_every_route` | `release.yml`, demo build in the docs image, docs pages, README |

**End of every phase:** `make test`, `make e2e`, the docs build plus `check_docs_anchors.py`, the `code-review` skill (medium), the step-10 registers, an EXECUTION_STATUS row, then commit (no-reply email, no attribution, secret scan) and push.

## New test seams and CI

**Seams:**
- **21** bundle contract (golden fixture, read and write);
- **22** console API (`TestClient`, real SQLite in tmp, real files, local git repos);
- **23** console UI (Playwright on the real stack in free mode, ports 1808x/1876x);
- **24** installer (vitest, a docker shim, `compose config`);
- **25** timed install (real images).

**CI:**
- `ci.yml`: the python job adds `services/console/tests` to the root `testpaths`. The ts job picks up `packages/create-voicecore` through `pnpm -r test`. A **new `console-e2e`** job mirrors `e2e`.
- `docker.yml`: a new path-filtered `installer` job. It builds the images as `:ci`, runs the CLI with `--image-tag ci`, then the install test.
- **New `release.yml`** (on tag `v*`):
  - buildx multi-arch push to GHCR (QEMU first; native ARM runners if the job takes over 30 min);
  - `npm publish --provenance` (trusted publishing);
  - an `install-timed` job on a clean runner that pulls the published images with a 600 s deadline. Its time is labelled "measured (CI runner, free mode)".
- `.github/dependabot.yml`: add the new directories.

## Security and ops risks (each with a test above)

- **Uploads:** size, file-count and expansion caps; extension allowlist; zip-slip guard; no symlinks; files that aren't UTF-8 are skipped and logged.
- **Git SSRF:** public addresses only, no redirects, time and size caps. DNS rebinding between check and clone remains possible; it is admin-only and documented.
- **Prompt injection in uploaded docs:** flagged sections are never quoted (`engine.py:139`), and the build log shows how many. Operator notes are appended after the grounding rules.
- **XSS:** `docs_url` must be http(s); the widget renders text nodes only (`widget.ts:63`).
- **Auth and CSRF:** as above.
- **Ops:**
  - cap each agent at 5,000 passages (embedding takes about 20 s per 1,000);
  - measure shared-embedder memory and image size, and publish the measured install time with its conditions;
  - the default VoiceCore-docs agent stays on customer installs (`--default-agent off` if anyone asks).
- **DX:**
  - Docker missing or not running → a specific message;
  - ARM → multi-arch images;
  - ports in use → the next free port;
  - Windows/WSL2 → untested, and documented as such;
  - the customer site's CSP must allow the voice host in `script-src` and `connect-src` (documented in the install guide).

## Files

**Create:**
- `docs/adr/0005-voicecore-platform.md`, `docs/step_10_voicecore_platform.md`, `docs/PLATFORM_PLAN.md`
- `services/agent-core/voicecore/agents.py`
- `services/console/{pyproject.toml, voicecore_console/{__init__,__main__,app,store,auth,sources,publish}.py, tests/*}`
- `apps/console/` (Vite + React + TS, `demo/*.json`, `e2e/console.spec.ts`)
- `packages/create-voicecore/{package.json,index.mjs,index.test.mjs,template/{compose.yml,Caddyfile}}`
- `fixtures/agents/`, `harness/install_smoke.py`, `harness/tests/test_install.py`
- `.github/workflows/release.yml`

**Modify:**
- `services/agent-core/voicecore/{server.py, budget.py, logs.py, metrics.py, answer/index.py, answer/engine.py, runtime/session.py, providers/deepgram_tts.py, providers/deepgram_stt.py}`
- `services/realtime-gateway/{session/server.go, session/session.go, session/prod.go, cmd/gateway/main.go, internal/fakeorch/fakeorch.go, Dockerfile}`
- `services/agent-core/Dockerfile`
- `apps/demo/src/widget.ts`, `apps/demo/e2e/check-mock-only.ts`
- `apps/docs/Dockerfile` (demo build at `/console/`)
- `packages/protocol/SPEC.md`
- `pyproject.toml`, `docker-compose.yml`
- `.github/workflows/{ci,docker}.yml`
- the master plan, `MASTER_AGENT_GUIDE.md`, ADR 0001, `EXECUTION_STATUS.md`, `README.md`

**Reuse rather than rewrite:**
- `ingest.ingest` and `SUSPICIOUS`, `check_url` (`answer/ingest.py`)
- `Index` (`answer/index.py`)
- `extractive.closest_section` (free mode)
- `handler_for(make_providers=)` (test injection, `server.py:202`)
- `budget.reserve_all` / sub-caps
- the `memnet` and `fakeorch` test helpers (Go)
- the `checkMockOnly` e2e guard
- the Playwright configs in `apps/demo`
- `scripts/csp.mjs`

**Docs and their effect on the assistant's corpus.** New pages:
- `getting-started/install.md` (the 10-minute quickstart)
- `guides/console.md`
- `reference/console-api.md`
- `architecture/control-plane.md`

Update `embed-the-widget.md` with `data-agent` and `/widget.js`. These pages change the assistant's corpus:
- the image vector bake picks up the new corpus hash automatically;
- check eval cases `a04` and `a11` in `fixtures/docs/voicecore_key.json`, and add an "install" question;
- re-running retrieval is free; the live assistant eval (about $0.03) waits for the owner's approval;
- `voicecore.fly.dev` needs a redeploy.

The static console demo sits outside `docs/`, so it doesn't touch the corpus.

## Money and outward actions

- **Money:**
  - all tests, the free mode and the timed install cost $0;
  - the optional live eval is about $0.03 (asked at the step);
  - the Fly demo costs $0 extra (it rides the existing docs app);
  - npm and GHCR are free.
- **The owner does, when asked:**
  - `npm login` (2FA) for the first publish, then trusted publishing;
  - switch the GHCR packages to public once;
  - approve the redeploys and the release tag.

## Verification (whole step)

1. `make test`, `make e2e`, the console e2e, the installer vitest and the Go tests are green. The docs build and anchor check pass.
2. On a clean machine: `npx create-voicecore --yes --mode free`, then set up the admin in the console → create "Acme Docs" → upload `fixtures/agents/acme.zip` → Publish → the Test tab answers `"Closest section: Refunds > How refunds work."` → paste the snippet into a plain HTML page served on another port, and the widget answers there.
3. Timed install under 600 s in CI, labelled with its conditions. The same flow answers with the console stopped.
4. Live mode, optional and approved: one spoken question to a bundle agent, with the agent's voice heard.
5. `voicecore-docs.fly.dev/console/` shows the read-only demo, and its Test tab answers through `voicecore.fly.dev`.
6. Before release: the `cso` and `security-review` skills, then `code-review` (high).

## Review record (2026-10-31)

**How it was run.** `/autoplan` was invoked, but its pipeline writes files outside the plan (restore point, snapshots, gate file, review logs) and its hook blocked the reviewer subagent, because plan mode allows edits only to this plan file. So its four lenses (CEO, design, developer experience, engineering) were run by hand against the plan and the code, all read-only. **No Codex or outside voice ran.** The design itself came from one independent Plan agent, which critiqued the first draft. The amendments are applied above.

**Scores, before → after the amendments:**
- **CEO / product: 6 → 8.**
  - The first-embed 403, the default agent leaking into customer installs, and having no upgrade or keys path would each have broken the "10 minutes".
  - Still open: free mode has no voice, so the "wow" needs keys. Mitigated by the installer recommending live and by the one-command `keys` upgrade.
- **Design: 5 → 8.** The first draft had no first-run guidance, build progress, empty states or demo affordances. Now added: the 4-step checklist, progress, empty states, the demo banner, labels plus an axe check, and screenshots at 375 px in both themes.
- **Developer experience: 6 → 9.** Added: Docker-not-running and Compose-version checks, re-run safety, `upgrade`, `keys`, `uninstall`, allowed websites without a restart, and an image-size budget.
- **Engineering: 7 → 9.**
  - The code claims were verified: per-`Index` model load (`index.py:45-53`), `CAPS` (`budget.py:17`), the global `OriginPatterns` (`server.go:401`), the query string in `Request.path`, and `closest_section` (`extractive.py:7`).
  - Added: a safe ledger read, SQLite WAL and migrations, and the bundle-format guard.

**Time to hello world** (target under 10 min; CI measures free mode on a runner, and live is measured once by hand, labelled `manual`):

| Step | Budget |
|---|---|
| `npx create-voicecore` download and questions | 0.5 min |
| Image pull (≤ 450 MB compressed at about 50 Mbit/s) | 1.5 min |
| `compose up --wait` (no default index to build) | 0.5 min |
| Admin setup and creating an agent | 1 min |
| Upload a zip, then Publish (embedding about 20 s per 1,000 sections) | 1.5 min |
| Test tab: ask one question | 0.5 min |
| Copy the snippet into the site and see the widget answer | 2 min |
| **Total** | **about 7.5 min**, with 2.5 min of margin |

**Failure modes registry:**

| Failure | Who sees it | Handling | Test |
|---|---|---|---|
| Docker missing or not running; old Compose | installer | a specific message plus the link, exit 1 | P8 vitest |
| Port in use | installer | next free port, printed | P8 |
| Embed blocked by Origin | site visitor | "Websites allowed to embed", reloaded without a restart | P5b Go |
| Publish interrupted halfway | voice users | atomic temp-folder rename plus `os.replace` of the pointer; the old version keeps serving | P1 prune/publish |
| Agent disabled during a token request | site visitor | `session.ended{unavailable}`, no spend | P2 |
| Bundle from a newer console | operator | clear format error; `upgrade` updates the data plane first | P5b |
| Console stopped | voice users | none: the data plane never calls the console | P9 |
| Ledger being rewritten while the console reads | console | `read_totals` with `LOCK_SH`, `O_RDONLY` | P5b |
| Zip-slip, zip bomb, huge body, symlink | console | 400/413 with the reason | P5, P7 |
| Git SSRF, redirect, LFS, oversized repo | console | hardened clone, public addresses only, caps | P7 |
| Injected instructions in uploaded docs | voice users | flagged and never quoted; count shown in the build log | P5 |
| Build interrupted by a restart | console | `running` → `failed: interrupted by restart` | P5 |
| Spend over the cap | voice users | `--pool public` falls back to text; caps from env | P8 |

**Not in scope:** SaaS, billing, tenant isolation, more than one admin, per-agent origins and caps, a URL crawler, `.mdx`, an agents CLI, a rollback UI, an S3 bundle store, Windows-native support.

**Already exists and is reused:** the ingest, index and extractive code, the sub-cap budget, the fakeorch and memnet test helpers, the e2e mock-only guard, the Playwright setups, `csp.mjs`, the Fly deploy, and the scale profile (for later multiple hosts).

**Decision audit trail** (auto-decided by the six principles; nothing here overrides an owner decision):

| # | Lens | Decision | Principle |
|---|---|---|---|
| 1 | Eng | Bundles on a shared volume, not an HTTP push between services | explicit over clever |
| 2 | Eng | Agent id is a token claim plus the upstream header; no per-agent origins in v1 | pragmatic |
| 3 | Eng | Origins for the whole install, reloaded from a file (added by the review) | completeness |
| 4 | Eng | One `Store` and plain functions, not nine ports | explicit over clever |
| 5 | Product | A new `--providers free` instead of mock for installs | completeness |
| 6 | Design | Real-snippet preview: iframe when self-hosted, inline widget in the demo | DRY |
| 7 | Developer experience | `upgrade`, `keys` and `uninstall` subcommands in the same package | completeness |
| 8 | Eng | Image budget of 450 MB compressed, enforced in CI | completeness |
| 9 | Product | Read-only demo as static snapshots on the existing docs app, $0 | pragmatic |

**Owner challenges:** none. The owner's decisions hold as stated.
