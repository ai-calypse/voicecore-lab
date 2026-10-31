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
  - provider keys exist only in the orchestrator's environment.

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
