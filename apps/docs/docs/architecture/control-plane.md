---
title: Control plane and data plane
description: How the VoiceCore console publishes agent bundles that the voice side reads, how a widget names its agent, and why voice keeps working when the console is down.
---

## Two halves with one contract between them

A self-hosted VoiceCore runs three services. The **console** is the control plane: it holds agents, their docs and settings, and builds versions. The **gateway** and the **orchestrator** are the data plane: they run voice sessions. The contract between the halves is a few files: the published agent bundles, the allowed websites, and the provider keys and spending limits set in the dashboard. The console writes them; the voice side mounts them read-only and never calls the console. So the console can be stopped, restarted or upgraded while conversations go on.

```text
 console ──publishes──▶ agents/<id>/<version>/ + agents/<id>/current ◀──reads── orchestrator
    │                    agents/_site/origins.json                    ◀──reads── gateway
    │──writes─────────▶ providers/keys.json, providers/limits.json    ◀──reads── orchestrator
    └── its own database (agents, sources, builds, API keys)
```

## What an agent bundle holds

A bundle is one folder per version: `config.json` (name, docs URL, instructions, first message, voice, model, key terms), `passages.jsonl` (the docs split into sections, with their URLs) and `vectors.npy` (one embedding per section). The version is a hash of the settings and the sections, so the same content always gets the same version. Publishing writes a temporary folder, renames it into place, then replaces the small `current` file that names the live version. A reader therefore never sees half a bundle. One module, `voicecore/agents.py`, owns the format; a version written by a newer console than the voice side understands is refused with a reason rather than read wrongly.

## How a session finds its agent

1. The widget's `data-agent` goes to the gateway with the request for a session token.
2. The gateway checks the id and that the agent has a live version, then signs the agent into the token, so a token cannot be pointed at another agent's settings and budget.
3. The gateway opens the session to the orchestrator with the agent in a header.
4. The orchestrator loads that agent's live version before reserving any budget. An unknown or turned-off agent ends the session as `unavailable`, at no cost.

Each new session reads the `current` file, so a publish reaches the next session with no restart. Conversations already open keep the version they started with. The orchestrator keeps recent versions loaded, and every agent's index shares one embedding model.

## Why this split, and what it costs

The split keeps the real-time path independent of the management path. The console's work, such as unpacking an upload or computing vectors for a large docs set, runs in its own process with a CPU limit, so it cannot slow the audio. Each half has only the access it needs: only the console can write bundles, keys and limits, and it never shows a provider key again once saved; the orchestrator reads them at each new session or reservation, so a change needs no restart. The cost is one more service and a shared volume, so this shape fits one machine. Several machines would sync the bundle folder, for example through object storage, without changing its format. Everything about one install, from the console and its single admin to the spend caps, belongs to one organisation; VoiceCore is self-hosted, not a shared service.
