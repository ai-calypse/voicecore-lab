# ADR 0005: VoiceCore platform: self-hosted console and agent bundles

**Status:** Accepted 2026-10-31 (owner decision). **Task:** S10-T00. **Amends:** the master plan's non-goals and [ADR 0001](0001-engine-ownership.md). [Plan](../PLATFORM_PLAN.md); evidence in the [step 10 registers](../step_10_voicecore_platform.md).

**Context.** Integrating VoiceCore today means cloning the repository, replacing a docs folder, setting flags and editing a deploy. The owner wants a company to go from nothing to a working voice assistant on its own site in about 10 minutes, the way ElevenLabs Agents works: a console to create agents and give them docs, a test button, and an embed snippet. The project stays a portfolio, not a SaaS.

## Scope

- **In:** a self-hosted, single-organisation console. One admin, created on first run, plus API keys. It indexes the organisation's own docs on the organisation's own hardware.
- **Out (unchanged):** SaaS plans, billing, tenant isolation, user accounts beyond one admin, and knowledge hosted by this project.

## Control plane and data plane

- **The console** (FastAPI and React) owns agents, knowledge sources, builds and API keys. It **publishes** immutable agent bundles to a shared `agents` volume.
- **The data plane** (gateway and orchestrator) reads that volume and never calls the console, so voice keeps working when the console is stopped.
- Volumes give least privilege:
  - the console alone writes `agents`;
  - the gateway and orchestrator mount it read-only;
  - provider keys live in the orchestrator's environment, or in the `providers` volume when set in the dashboard (amended 2026-11-01, below).

## Agent bundle format v1

- **Owner:** `voicecore/agents.py` is the only owner of the format; the console imports it.
- **Layout:** `agents/<id>/<version>/{config.json, passages.jsonl, vectors.npy}`, plus the pointer file `agents/<id>/current`.
- **Version:** `version = sha256(config + corpus)[:12]`, so the same content always gives the same version.
- **Publishing** is atomic: write a temporary folder, rename it, then replace the pointer with `os.replace`. A reader never sees a half-written bundle, and the last 5 versions are kept.
- **Disabling** an agent removes its pointer.
- **`config.json`** holds `format`, `name`, `docs_url`, `instructions`, `first_message`, `voice`, `llm` and `keyterms`. Voice and model must come from fixed catalogs, so cost estimates stay correct.
- **Format guard:** a reader rejects a format it does not know with "bundle format N needs a newer voicecore image". An upgrade updates the data plane first.

## How an agent is chosen

1. The widget's `data-agent` is sent as the form field `agent` on `POST /v1/session`.
2. The gateway checks the id (`^[a-z0-9][a-z0-9-]{0,39}$`). If `agents/<id>/current` does not exist, it answers 404.
3. The gateway signs the agent into a 4-part token, `exp.nonce.agent.HMAC`. A token without an agent keeps the 3-part form, byte for byte, so existing clients and deploys do not change.
4. The upstream dial carries the agent in the `X-VoiceCore-Agent` header. A query string would break the session id parsing, because the websockets `Request.path` includes it.
5. The orchestrator resolves the agent **before** reserving any budget, then loads the version named by the pointer. Each new session reads the pointer; open sessions keep the bundle they started with.
6. Every `Index` shares one embedding model.

## Install-wide settings

- **Allowed websites:** the console publishes them to `agents/_site/origins.json`. The gateway adds them to its origin checks, reloading the file when it changes, so a new website needs no restart.
- **Spend caps:** come from environment variables, with the project's own caps as defaults.
- **`--providers free`:** text answers from the organisation's own docs (extractive), at no cost, so the install works before any provider key exists.

## Deferred, with triggers

- Per-agent origins and caps: when two agents need different limits.
- A URL crawler, `.mdx`, an agents CLI, a rollback UI, an S3 bundle store: when a real user needs them.

## Consequences

- One more Python service, the console, and two published images: `voicecore` and `voicecore-gateway`.
- The token format gains an optional agent part. `SPEC.md` §4 documents it; the event vectors are unchanged.
- The default agent (this repository's docs) stays the behaviour when no agent is given. Customer installs turn it off with `--default-agent off`.

## Amendment, 2026-11-01: provider keys in the dashboard

The owner asked for the provider keys to be managed from the dashboard, like the rest of an install. The console now writes keys entered on its Voice page to a `providers` volume (`keys.json`, mode 600); the orchestrator mounts it read-only and reads it at each new session, ahead of its environment (`voicecore.keys`). With `--providers auto`, a session is live once both keys are present and free otherwise, so a key added in the dashboard turns voice on for the next conversation, with no restart. The data plane still never calls the console.

- **What changes for least privilege:** the console now holds provider keys. It never returns them (only their last four characters), checks each with one free call to its provider before saving it, and needs a signed-in admin to change them. Someone with the admin password could replace a key, which would redirect spend to their own provider account, not read the owner's key.
- **Why not leave keys in `.env`:** changing them needed a terminal and a restart, the step the owner found hardest. Keys in `.env` or the environment (Fly secrets) still work, and a dashboard key takes their place.

## Amendment, 2026-11-01: the four steps that stayed hard

Asked whether the setup was as simple as it could get, the owner chose to remove the four hardest steps.

- **Docs from a website address.** The deferred URL crawler, triggered by this request: most website owners' docs are their website. A `web` source reads the page at a public https address and every page linked below it on the same host (same folder or deeper), up to 200 pages in 60 s and 20 MB. Every address, redirects included, passes the same public-address check as the Git source (`check_url`); a redirect off the host is not followed; scripts never run. Pages keep their own address (`source_url`), so answers link to them. Pages that need JavaScript to show text cannot be read, and the console says so. The remaining risk is the Git source's: DNS can change between the check and the request (admin-only, documented).
- **Allowed websites added for you.** A website read as docs, or a new Docs URL, is added to the allowed websites (with its `www` twin), since that is where the button will go. The console says what it added. Removing it sticks until the admin reads that website again or sets a new Docs URL.
- **Spending limits in the dashboard.** The console writes `providers/limits.json`; the orchestrator reads it at each reservation (`budget.apply_limits`), so a change needs no restart. The dashboard's total replaces the public sub-cap's, and lifts the pool's cap when it is higher; the pool's own cap from the environment stays its floor. New installs start at $1 a day and $10 in total (about 100 and 1,000 questions), up from $0.50 and $2, which stopped a real website after about 50 questions.
- **No DNS step.** `create-voicecore --domain auto` serves the install on the server's own IP address with a Let's Encrypt certificate for that address (the 6-day `shortlived` profile, generally available since January 2026; Caddy 2.11 renews it). A shared wildcard DNS name such as sslip.io was rejected: it is not on the Public Suffix List, so every user of it shares one Let's Encrypt rate limit, which reports show exhausted. A one-line `install.sh` installs Docker (Docker's own script) and Node.js (the official build, checksum checked) on a Linux server, then runs the installer with `--domain auto`. A domain of one's own stays optional and survives a move to a new server; the IP address does not.
- **Not done:** a "Deploy" button for a hosting platform, until one is tried end to end; a hosted VoiceCore, which this ADR rules out.
