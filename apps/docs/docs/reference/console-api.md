---
title: Console API
description: Every route of the VoiceCore console's HTTP API - sign-in, API keys, agents, knowledge sources, publishing, websites and spend - with how to call it from a script.
---

## How to call the console API

The console's web pages use this API, and scripts can too. A running console also serves the live reference at `/api/docs`. Requests and responses are JSON, except an upload, whose body is the file itself. There are two ways to authenticate:

- **API key**, for scripts and CI: `Authorization: Bearer vck_...`, made on the console's API keys page.
- **Session cookie**, for the browser: set by `/api/setup` or `/api/login`.

A changing request that names another site in its `Origin` header is refused with 403 `cross-origin request`. An error answers with `{"detail": "..."}`, a reason the console shows as it is.

```bash
KEY=vck_...
curl -s -H "Authorization: Bearer $KEY" http://localhost:8000/api/agents
curl -s -H "Authorization: Bearer $KEY" -H "Content-Type: application/octet-stream" \
     -X PUT --data-binary @docs.zip "http://localhost:8000/api/agents/acme-docs/sources/upload?name=docs.zip"
curl -s -H "Authorization: Bearer $KEY" -X POST http://localhost:8000/api/agents/acme-docs/publish
```

## Routes for sign-in and keys

| Method | Route | What it does |
|---|---|---|
| GET | `/api/status` | whether setup is needed, the provider mode and the voice server's address; no sign-in needed |
| POST | `/api/setup` | first run: `{token, password}` makes the admin, once |
| POST | `/api/login` | `{password}`; at most 5 attempts a minute per address |
| POST | `/api/logout` | ends this session |
| GET | `/api/me` | 200 when signed in |
| GET | `/api/keys` | the API keys, without the keys themselves |
| POST | `/api/keys` | `{label}`: a new key, shown in this response only |
| DELETE | `/api/keys/{key_id}` | revokes a key at once |

## Routes for agents and their docs

| Method | Route | What it does |
|---|---|---|
| GET | `/api/agents` | every agent with its live version, latest build status, number of sources, and what was last published and when |
| POST | `/api/agents` | `{name}`: a new agent; its id is made from the name |
| GET | `/api/agents/{agent_id}` | settings, sources, latest build, last published build, live version and the embed snippet |
| PUT | `/api/agents/{agent_id}/settings` | name, docs URL, first message, instructions, voice, model, key terms and turn-taking (`quick` or `patient`); checked, used at the next publish |
| DELETE | `/api/agents/{agent_id}` | the agent, its docs and its versions |
| PUT | `/api/agents/{agent_id}/sources/upload` | `?name=file.zip`, body: a zip, `.md`, `.markdown` or `.txt` file, up to 20 MB |
| POST | `/api/agents/{agent_id}/sources/text` | `{title, text}`: a page from pasted text |
| POST | `/api/agents/{agent_id}/sources/git` | `{url, folder, ref}`: one folder of a public https repository |
| POST | `/api/agents/{agent_id}/sources/{source_id}/sync` | fetches a Git source's folder again |
| DELETE | `/api/agents/{agent_id}/sources/{source_id}` | removes a source |
| POST | `/api/agents/{agent_id}/publish` | starts a build (202); 409 while one is running |
| GET | `/api/agents/{agent_id}/builds/latest` | status, sections done of total, version and log |
| POST | `/api/agents/{agent_id}/disable` | new sessions for the agent are refused at once |
| POST | `/api/agents/{agent_id}/enable` | puts the last published version back |
| GET | `/preview/{agent_id}` | the Test page: exactly the embed snippet, framed by the console only |

## Routes for the whole install

| Method | Route | What it does |
|---|---|---|
| GET | `/api/site` | the websites allowed to embed the assistant |
| PUT | `/api/site` | `{origins: ["docs.example.com"]}`; the voice server reads it within a second |
| GET | `/api/usage` | provider spend recorded by the voice server's ledger, and the caps |
| GET | `/api/catalog` | the voices and models an agent may use |
