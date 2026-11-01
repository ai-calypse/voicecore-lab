# Step 10: VoiceCore Platform

**Status:** Built (P0–P9, 2026-10-31). Waiting on the owner: npm and GHCR publishing and the first release tag, the docs redeploy for the console demo, and the final security reviews.
**Estimated engineering effort:** about 87 hours.
**Task owner:** Implementation agent. The owner decides on npm and GHCR publishing (`npm login`, making packages public), release tags, redeploys and any live spend.

## Purpose and scope

Make VoiceCore something any company can install and integrate in about 10 minutes, in the way ElevenLabs Agents works:

- `npx create-voicecore` installs the stack with Docker;
- a console creates agents and gives them docs (file upload, a Git repository, pasted text);
- a Test tab asks the agent a question;
- one `<script>` tag embeds it on the company's site.

The architecture is a control plane (the console) that publishes immutable agent bundles, and a data plane (gateway and orchestrator) that only reads them. See [ADR 0005](./adr/0005-voicecore-platform.md).

**Non-goals** ([ADR 0005](./adr/0005-voicecore-platform.md)):

- SaaS plans, billing, tenant isolation;
- user accounts beyond one admin;
- knowledge hosted by this project;
- per-agent origins and caps, a URL crawler, an agents CLI (deferred with triggers).

## Step-specific implementation-agent prompt

> Act as a senior engineer building a developer product.
>
> Read [`docs/PLATFORM_PLAN.md`](./PLATFORM_PLAN.md) (approved 2026-10-31, review record included), [ADR 0005](./adr/0005-voicecore-platform.md) and the actual code. Implement the phases in order, one RED → GREEN → COMMIT slice at a time, with the literal expected values from the plan.
>
> Never publish to npm or GHCR, tag a release, or redeploy without the owner. Never add attribution lines to commits.

## Required reading and prerequisites

- [Platform plan](./PLATFORM_PLAN.md): phases, slices, seams 21–25, failure modes.
- [Implementation plan §A](./IMPLEMENTATION_PLAN.md): the TDD rules, which still bind.
- ADRs [0001](./adr/0001-engine-ownership.md) (amended 2026-10-31), [0004](./adr/0004-deploy-abuse-resilience-scale.md) and [0005](./adr/0005-voicecore-platform.md).
- Step 09 outputs, as recorded in [EXECUTION_STATUS.md](../EXECUTION_STATUS.md).

## Decision ownership

This step owns:

- the agent bundle format v1;
- the 4-part agent token and the `X-VoiceCore-Agent` upstream header;
- `--providers free`;
- the console API and its auth;
- the installer's commands and files;
- the published image names;
- [ADR 0005](./adr/0005-voicecore-platform.md).

A change to the token or the upstream contract updates `packages/protocol/SPEC.md` in the same slice.

## Phases and specific tasks

| Task | Plan phase | Outcome |
|---|---|---|
| S10-T00 | P0 | Scope amendment (master plan, guide, ADR 0001), ADR 0005, this step doc, plan copy, status rows |
| S10-T01 | P1 | Answer-engine prerequisites: `Index(vectors=)`, one shared embedder, `voicecore/agents.py` (bundle read, write, publish, prune) |
| S10-T02 | P2 | Orchestrator per agent: `--agents-dir`, `--providers free`, greeting, operator notes, voice and keyterm URLs, agent labels |
| S10-T03 | P3 | Gateway and widget: agent token, unknown-agent 404, upstream header, `/widget.js`, `data-agent` |
| S10-T04 | P4 | Console core and auth: first-run setup, login, sessions, API keys, reset-admin |
| S10-T05 | P5 | Agents, sources (upload, text), builds and publish |
| S10-T06 | P5b | Allowed websites without restart, safe ledger read, console migrations, bundle format guard, default agent off |
| S10-T07 | P6 | Console UI: setup, agents, knowledge, settings, test, embed, API keys; checklist, progress, empty and demo states |
| S10-T08 | P7 | Git source with a hardened clone |
| S10-T09 | P8 | Images, `create-voicecore` (install, upgrade, keys, uninstall), caps from env, Caddy profile |
| S10-T10 | P9 | Release workflow, timed install under 10 minutes, read-only demo, docs and README |

## Risks, verification and recovery

The plan's failure-modes registry lists each risk with its handling and its test. The main ones:

- untrusted uploads and Git URLs;
- prompt injection in uploaded docs;
- the first embed blocked by the Origin check;
- image size against the 10-minute promise.

Recovery from a bad publish is a pointer flip, because the last 5 versions are kept.

## Acceptance checklist

- [ ] `npx create-voicecore --yes --mode free` on a clean machine installs a working stack. (verified from a clone with locally built images; the published package needs the first release)
- [x] Setup → create agent → upload → Publish → Test tab gives a cited answer; the copied snippet answers on another page. (console e2e; `apps/demo/e2e/agent.spec.ts` on another page)
- [ ] The timed install is under 600 s in CI, labelled with its conditions.
- [x] Voice keeps answering with the console stopped. (`harness/install_smoke.py`, local images)
- [ ] The read-only demo is live at `voicecore-docs.fly.dev/console/`.
- [ ] `make test`, `make e2e`, the console e2e, the installer tests and the Go tests are green; the docs anchor check passes.
- [ ] The `cso`, `security-review` and `code-review` (high) skills have run, and their findings are fixed.

## Decisions and outputs register (fill in during implementation)

| Date | Task | Decision / output | Evidence |
|---|---|---|---|
| 2026-10-31 | S10-T00 | Scope amended: a self-hosted single-organisation console is in; SaaS, billing, tenants and extra accounts stay out | ADR 0005; master plan non-goals; ADR 0001 amendment |
| 2026-10-31 | S10-T01 | Bundle format v1 (`voicecore/agents.py`); `Index(vectors=)`; one embedding model per process; `embed()` with progress | `test_bundle.py`, golden fixture `fixtures/agents/acme-docs/` |
| 2026-10-31 | S10-T02 | `X-VoiceCore-Agent` picks the bundle before any reservation; `--providers free`; greeting, operator notes after the rules, voice and key-term URLs; agent id in logs and traces | `test_agent_runtime.py` (14) |
| 2026-10-31 | S10-T03 | 4-part agent token (3-part unchanged), 404 unknown / 400 bad id, upstream header, `/widget.js`; widget `data-agent`, endpoint from the script's origin | Go `agent_test.go`; Playwright `agent.spec.ts`; SPEC.md §4 |
| 2026-10-31 | S10-T04 | One admin via setup token, scrypt, SameSite=Strict cookie, login limit, cross-origin refusal, hashed API keys, reset-admin | `test_console_auth.py` (10) |
| 2026-10-31 | S10-T05 | Agents, uploads (20 MB body, 50 MB unpacked, zip-slip), pasted text, one build thread, atomic publish, enable/disable | `test_console_agents.py` (16) |
| 2026-10-31 | S10-T06 | Allowed websites published to `agents/_site/origins.json`, re-read by the gateway within 1 s; `budget.read_totals`; schema v2; format guard | Go origins tests; `test_console_site.py`; `test_bundle.py` |
| 2026-10-31 | S10-T07 | Console UI (React, no router or kit) and `/preview/<id>`; preview fitted to the viewport after the e2e found the launcher below the fold | `apps/console` e2e (2), vitest (3) |
| 2026-10-31 | S10-T08 | Git sources: hardened sparse clone of one folder, public addresses only (`check_url(allowed=None)`) | `test_console_git.py` (7), local repos only |
| 2026-10-31 | S10-T09 | `create-voicecore` (install, upgrade, keys, uninstall), compose template with a Caddy public profile, caps from env, `-human-check off`, two images | installer vitest (11); `test_install.py` (2): install to cited answer 13.5 s from local images, voicecore image 231 MB compressed |
| 2026-10-31 | S10-T10 | Docs pages (install, console, console API, control plane), configuration and embed updates, eval cases a04/a11 widened (no new case: it would change the pinned live-load fixture count), read-only demo at `/console/` from API snapshots, release workflow | `test_console_reference.py`; `test_demo_snapshot.py`; docs Playwright `console-demo.spec.ts`; anchor check 362 passages / 31 pages, 0 broken |

## Execution record

| Date | Phase | Commands and results |
|---|---|---|
| 2026-10-31 | P0–P9 | `make test-py`: 277+ passed; Go `go test -race ./...` passed; `pnpm test` (all TS packages) passed; `apps/demo` e2e (agent spec) and `apps/console` e2e passed; docs build and anchor check passed; `harness/tests/test_install.py -m docker` 2 passed locally |
| 2026-10-31 | CI | Found and fixed: the voice images failed `uv sync --locked` once the console joined the workspace (`890c79b`); the console's vitest picked up the Playwright spec and a fakeorch test raced its listener (`8235c08`) |
| 2026-10-31 | Not verified | The console screenshots were captured but not reviewed by eye: the session's `/autoplan` hook (bun not on the hook's PATH) blocked image reads. The published install (npm, GHCR) waits for the first release |
| 2026-10-31 | Console design pass (owner request) | Second pass after owner feedback (calm monochrome, sidebar, Home overview, like current product consoles): grey canvas, white panels, black primary buttons, status dots; sidebar navigation; Home with real tiles (agents live, spend, voice, websites) and the agents table; New agent in a dialog. Reviewed by eye in light, dark and at 375 px (no horizontal scroll) against a local free-mode install. Agents list shows what each agent has and when it was published (`GET /api/agents` gains `sources`, `summary`, `published`; `GET /api/agents/{id}` gains `published`); the getting-live steps became one track that marks the next step and steps aside when all four are done; Knowledge puts sources and adding docs (one method at a time) beside the live version; Settings in two groups; the docs site's logo. `test_console_agents.py` (18), vitest (5), console e2e (2), docs e2e (4), `make test-py` 282 passed, anchor check 0 broken |
| 2026-11-01 | First real integration (owner request): the owner's portfolio | Local install from the repo's installer into `portfolio/voicecore` (free mode); a portfolio agent built from the site's own content; the site deployed on Vercel with the snippet; the Fly app now serves `/widget.js` and agents from `AGENTS_DIR` on its volume, so the portfolio agent answers live (Deepgram + OpenRouter). Found and fixed: the widget had no way to avoid a page's own bottom-right button (`data-position="left"`), the installer left `.env` committable (writes `.gitignore`), "1 pages". Verified: widget e2e (9), installer vitest (11), Fly image tests (4, one new), a live typed answer from the portfolio agent on Fly citing the Vercel page. Waiting on the owner: the Vercel host in the Turnstile widget's hostnames |
| 2026-11-01 | Simpler integration (owner request: "no easy way to know the dashboard link and password, not live by default") | The hosted deploy runs the console too: the gateway passes every path it does not serve to it (`-console`, with the visitor's address and scheme), so `https://voicecore.fly.dev/` is the dashboard and publishing there puts an agent live with no copying or deploy. The admin password comes from `CONSOLE_ADMIN_PASSWORD` (a changed one signs everyone out); the installer generates it, is live by default (keys from the prompt or the environment, free mode without them), prints the dashboard address and password, and `create-voicecore info` shows them again. The console frees the embedding model after each publish (about 60 MB idle) to fit the 1 GB machine, with 512 MB of swap as a margin. Per-agent turn-taking (owner's report of cut-off words): `patient` uses a fixed 800 ms of silence. Verified: Go `go test -race ./...` (2 new), console tests 57 (5 new), agent runtime (2 new), installer vitest 14 (4 new), console e2e 2, Fly image tests 5 (1 new: publish through the dashboard on the gateway's port, then a token for that agent), `make test-py` 290 passed, eval gate passed, anchor check 0 broken |
| 2026-11-01 | Deployed (`0a348a4`) | `https://voicecore.fly.dev/` serves the dashboard (admin password a Fly secret). The portfolio agent was rebuilt there (Patient turn-taking, key terms without the everyday word "Aloud"), published as `3b99fc00e7c8`, and its website moved from `ORIGINS` to the dashboard's Allowed websites. A typed question on the machine got a cited answer from that version (`#callstorm`). The portfolio now carries the dashboard's snippet as is, with no environment variables. Found and fixed by hand: the agent folder copied in earlier as root blocked the console's publish (one `chown`; the dashboard is now the only way agents arrive). Not verified: the Test tab's Turnstile check from a real browser (a headless browser is refused either way) |
| 2026-11-01 | Provider keys in the dashboard (owner request), installer 0.2.0 | A Voice page saves the Deepgram and OpenRouter keys after one free check with each provider (`/v1/auth/token`, `/api/v1/key`), write-only (last four characters back), to a `providers` volume the orchestrator reads at each new session ahead of its environment; `--providers auto` makes a session live once both keys exist. The installer asks one question (a domain, or this machine), drops `--mode` and `keys`, and `info` reads voice from the dashboard's status. ADR 0005 amended. v0.1.0 released first (images, npm by hand, trusted publishing set up; the timed install from the published images took 25 s). Verified: `make test-py` 301 passed, console tests 59 (7 new), keys (2 new), auto mode (2 new), installer vitest 14, console e2e 2, Docker install test 2 on rebuilt images, a wrong Deepgram key refused and the real keys accepted (voice on) through a local console, Voice page by eye in light at 1280 px and dark at 375 px, eval gate, anchors 0 broken |
| 2026-11-01 | Plain-language setup docs (owner request) | `getting-started/install.md` rewritten as "Add VoiceCore to your website": eleven steps from an empty server to a working button, what it costs (about 1 cent a spoken question, an estimate from list prices), the spending limits and what they mean for concurrent conversations (up to $0.18 set aside per conversation), upkeep and a symptom table using the widget's real messages. The console guide became "Use the dashboard", one plain section per page; the widget page now opens with the dashboard's one-line snippet; the intro points to the guide. Found and fixed: the console container did not get the spend caps, so the Home spend line would show the defaults after they were raised. Verified: docs build, anchors 380 passages / 0 broken, eval gate, the pages by eye at 1280 px and 375 px (no horizontal scroll) |
| 2026-11-01 | A prompt for the reader's AI agent (owner request) | The guide opens with a copyable prompt that points an AI assistant at the guide, asks it to go one step at a time, add the snippet in the reader's project, and never ask for keys in chat. Docusaurus's own code-block copy button, kept visible and the text wrapped by two CSS rules scoped to that block (the page stays CommonMark, so the eval key's `install.md` path holds). Verified: the button copies the 10-line prompt, no overflow at 1280 px or 375 px, docs build, anchors 381 / 0 broken, eval gate |
| 2026-11-01 | The four hard steps removed (owner request: "is this the simplest we can get?") | **Docs from a website address:** a `web` source (`sources.fetch_web`) reads the page at a public https address and every page linked below it on the same host, up to 200 pages, 60 s and 20 MB; each address and redirect passes `check_url`; menus, headers outside the article, footers and scripts are dropped; pages keep their real address and heading ids, so answers link to them; Sync reads the site again. **Allowed websites added for you:** reading a website, or a new Docs URL, adds that site and its `www` twin, and the console says so. **Spending limits on the Voice page:** `PUT /api/limits` writes `providers/limits.json`; `budget.apply_limits` reads it at each reservation, no restart; new installs start at $1 a day and $10 in total. **No DNS step:** `create-voicecore --domain auto` serves `https://<server IP>` with a Let's Encrypt IP certificate (`shortlived` profile, Caddy 2.11, `default_sni`); sslip.io rejected (not on the Public Suffix List, so one shared rate limit, reported exhausted). `install.sh` installs Docker and Node.js (checksum checked) on a Linux server and runs the installer; the installer waits up to 120 s for https and names the ports to open if it doesn't answer. Installer 0.3.0. Docs: the setup guide is eight steps, plus "Use a web address of your own"; dashboard guide, API reference, configuration, control plane, README, ADR 0005 amendment. Code review (medium): 10 findings; fixed 9 (a left-out menu or form with optional end tags hid the rest of the page; SVG icon titles in the page title; `role=main` never closed; an unknown charset failed the whole read; the address actually connected to is now checked as public too, against DNS rebinding, though the request has been sent by then; a re-sync to a new host now allows it; the website field accepted no address without `https://`; the spend line compared all spend with the public limit; a lower dashboard total squeezed the pool, whose own cap is now the floor). Verified: `make test` (pytest 319, TS 56, Go); console e2e 3 (adds the limits); a real read of docs.astral.sh, 5 pages in 0.7 s, 41 sections linking to the site's own anchors; docs build, anchors 380 / 0 broken, docs e2e 4 (the demo summary now read from its snapshot); latency gate; `install.sh` on a clean ubuntu:24.04 (real Node.js download and checksum, Docker and npx stood in); Caddyfile adapted and validated by caddy:2.11 for a domain and an IP; Voice and Knowledge pages by eye at 1280 px light and 375 px dark, no horizontal scroll. Not verified: a real Let's Encrypt IP certificate on a public server (needs a server reachable on ports 80 and 443), and a crawl of a real website from the console |

## Source and artifact change record

| Date | Paths | Why |
|---|---|---|
| 2026-10-31 | `docs/PLATFORM_PLAN.md`, `docs/adr/0005-voicecore-platform.md`, this file, master plan, `MASTER_AGENT_GUIDE.md`, ADR 0001, `docs/README.md`, `EXECUTION_STATUS.md` | S10-T00: scope and records |

## Handoff

Step 10 is complete when every acceptance item is checked with evidence in the registers above and in [EXECUTION_STATUS.md](../EXECUTION_STATUS.md).
