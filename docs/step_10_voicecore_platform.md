# Step 10: VoiceCore Platform

**Status:** In progress (started 2026-10-31).
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

- [ ] `npx create-voicecore --yes --mode free` on a clean machine installs a working stack.
- [ ] Setup → create agent → upload → Publish → Test tab gives a cited answer; the copied snippet answers on another page.
- [ ] The timed install is under 600 s in CI, labelled with its conditions.
- [ ] Voice keeps answering with the console stopped.
- [ ] The read-only demo is live at `voicecore-docs.fly.dev/console/`.
- [ ] `make test`, `make e2e`, the console e2e, the installer tests and the Go tests are green; the docs anchor check passes.
- [ ] The `cso`, `security-review` and `code-review` (high) skills have run, and their findings are fixed.

## Decisions and outputs register (fill in during implementation)

| Date | Task | Decision / output | Evidence |
|---|---|---|---|
| 2026-10-31 | S10-T00 | Scope amended: a self-hosted single-organisation console is in; SaaS, billing, tenants and extra accounts stay out | ADR 0005; master plan non-goals; ADR 0001 amendment |

## Execution record

| Date | Phase | Commands and results |
|---|---|---|

## Source and artifact change record

| Date | Paths | Why |
|---|---|---|
| 2026-10-31 | `docs/PLATFORM_PLAN.md`, `docs/adr/0005-voicecore-platform.md`, this file, master plan, `MASTER_AGENT_GUIDE.md`, ADR 0001, `docs/README.md`, `EXECUTION_STATUS.md` | S10-T00: scope and records |

## Handoff

Step 10 is complete when every acceptance item is checked with evidence in the registers above and in [EXECUTION_STATUS.md](../EXECUTION_STATUS.md).
