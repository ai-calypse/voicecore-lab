---
title: Privacy
description: What the docs assistant does with your voice and questions, what is kept, and for how long.
---

# Privacy

This page covers the voice assistant on this site ("Ask the docs"). VoiceCore Lab is a portfolio project, not a commercial service.

## Your microphone and voice

- The microphone is used only after you press the mic button. It stops when you press it again or close the assistant.
- Your audio streams to the VoiceCore gateway and orchestrator, which pass it to **Deepgram** to turn speech into text.
- **VoiceCore does not store your audio.**

## Your questions and the answers

To answer a question, VoiceCore sends these to the language model, **gpt-oss-120b**, through **OpenRouter**, which runs it on **Cerebras**:

- your question as text;
- the passages of these docs that match it;
- the last two questions and answers of the same conversation.

The answer text goes to **Deepgram** to be spoken. The passages are found on VoiceCore's own server; your question is not sent anywhere else for that.

**VoiceCore does not store your questions or the answers.** They appear only in the assistant's panel, and are gone when you close the tab.

Each provider handles what it receives under its own privacy policy: Deepgram (audio and answer text), OpenRouter and Cerebras (questions and passages).

## What VoiceCore keeps

| What | Contains | How long |
|---|---|---|
| **Spend record** | The cost of each session, its session id, the provider's request id. **No audio, no text.** | Kept: it is how VoiceCore enforces its spending caps. |
| **Service logs** | Session started or ended, with session id, reason and duration; provider error types. **No audio, no text, no IP addresses, no keys.** | Depends on the deployment; see below. |
| **Web server access log** (this site) | Your IP address, the page requested and your browser's user agent | Same as the service logs. |
| **Rate limits** | Your IP address, to limit how many sessions one address can start | In memory for the day. With several servers, in Redis for up to 48 hours. |

Detailed session traces exist for development. They are off in production, and even when on they leave out questions and answers unless a developer turns that on for a test.

### Log retention by deployment

- **Running locally** with the monitoring stack: logs are kept for **7 days**, then deleted.
- **On Fly.io**, if deployed: Fly keeps application logs for about **7 days** (Fly's documentation, checked 2026-10-30). There is no other log store there.

## Your browser

The assistant sets no cookies and uses no local storage. Its session details live in the page's memory and are gone when you close the tab.

If this site turns on Cloudflare Turnstile (a check that you are a person, before a session starts), Cloudflare receives signals from your browser under Cloudflare's own privacy policy. It is off unless the site sets it up.
