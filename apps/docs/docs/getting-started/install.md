---
title: Install VoiceCore for your own docs
sidebar_label: Install for your docs
description: Install VoiceCore with one command, add your docs in the console, test the assistant and put it on your website, in about ten minutes.
---

## What you need before installing

You need a computer or server with Docker running (Docker Compose 2.20 or newer) and Node.js 20 or newer for the one-command installer. Nothing else: the installer downloads two images, VoiceCore's own (`ghcr.io/ai-calypse/voicecore`, about 230 MB compressed) and its gateway (about 5 MB). For voice, you also need a Deepgram API key (speech in and out) and an OpenRouter API key (the language model); you add them in the dashboard after installing. Until both are there, VoiceCore answers typed questions with the closest section of your docs, at no cost.

## Install with one command

```bash
npx create-voicecore
```

The installer checks Docker and asks one question: a public domain for VoiceCore, or Enter to run it on this machine only. It writes everything into a `voicecore` folder (a `compose.yml`, a `Caddyfile` and a private `.env` with generated secrets), starts the stack, and ends by printing the dashboard's address and its password:

```text
VoiceCore is running.

  Dashboard  http://localhost:8000
  Password   q3Vx9LdT2pWn7KcR0bYa
  Voice      off: add your Deepgram and OpenRouter keys on the dashboard's Voice page
```

The password is generated for this install and kept in its `.env` as `CONSOLE_ADMIN_PASSWORD`. Run `npx create-voicecore info` in the same folder to see the address and password again. `npx create-voicecore --yes` asks nothing and installs on this machine.

On this machine, the dashboard listens on `http://localhost:8000` and the voice server on `http://localhost:8080`, reachable from this machine only. If a port is busy, the installer takes the next free one and prints it. With a domain (`--domain voice.example.com`), both sit behind one HTTPS host, with Caddy getting and renewing the certificate; the domain's DNS must point at the server, with ports 80 and 443 open. Add Cloudflare Turnstile, a human check on new sessions, with `--turnstile-sitekey` and `--turnstile-secret`; without it the rate limits and spend caps still apply.

## Sign in to the dashboard and add your docs

Open the dashboard address the installer printed and sign in with its password. Create an agent and give it docs on its Knowledge tab, in any of three ways:

- **Upload files:** Markdown (`.md`, `.markdown`), plain text, or a zip of a docs folder, up to 20 MB.
- **A Git repository:** a public repository over https and the folder that holds the Markdown.
- **Paste text:** a title and some text, for an FAQ or a short note.

On the Settings tab, set **Docs URL** to where these docs are published, so answers link to the section they cite. Then press **Publish**. VoiceCore splits the docs into sections at their headings, computes a vector for each section, and puts the new version live. The console shows the progress, for example "Embedding 120 of 342 sections".

## Turn on voice

On the dashboard's **Voice** page, paste a Deepgram key and an OpenRouter key. VoiceCore checks each one with its provider when you save it, and the next conversation speaks and listens, with no restart. A saved key is never shown again, only its last four characters. For a scripted install, pass the keys with `--deepgram` and `--openrouter`, or set `DEEPGRAM_API_KEY` and `OPENROUTER_API_KEY` in the environment before running the installer; they go to `.env`.

## Test the agent and put it on your website

The **Test** tab holds a page with exactly the snippet your site will use. Open the assistant in its corner and ask a question from your docs.

The **Embed** tab gives one line to paste before `</body>` on your pages:

```html
<script src="http://localhost:8080/widget.js" data-agent="acme-docs" async></script>
```

The voice server serves the widget itself, and the widget talks to the server that served it. Add your website under **Allowed websites** in the dashboard, or browsers on it are refused. The change takes effect within a second, with no restart.

## Upgrade or remove VoiceCore

| Command | What it does |
|---|---|
| `npx create-voicecore info` | shows the dashboard's address and password, and whether voice is on |
| `npx create-voicecore@latest upgrade` | newer images with the same settings, agents and docs |
| `npx create-voicecore uninstall` | stops VoiceCore and keeps its data; add `--delete-data` to remove agents, docs and the spend ledger too |

## How long the install takes

On one Apple M4 laptop with the images already downloaded, the measured path from running the installer to a cited answer through the voice server took 13.5 s: 12.3 s for the install and start, 1.2 s for signing in, an upload of the three-section Acme sample and its publish. A first install adds the image download, about 230 MB. CI runs the same path on every change and fails it past ten minutes.
