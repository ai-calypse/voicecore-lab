---
title: Use the console
description: Manage VoiceCore agents in the console - knowledge sources, publishing and versions, settings and turn-taking, the Test and Embed tabs, allowed websites, API keys and the admin password.
---

## What an agent is

An agent is one voice assistant: a set of docs, the settings it answers with, and a live version. One VoiceCore install can run several agents, for example one per product, each with its own snippet. The console opens on Home: how many agents are live, spend against the cap, whether voice is on, and which websites are allowed to run an agent. Until an agent is live and on your site, its page shows four steps with a tick when each is done: **Add docs**, **Publish**, **Test** and **Embed**. The steps go away once all four are done. The Knowledge tab also shows the live version: how many sections it holds, when it was published and its version.

## Add knowledge sources to an agent

The Knowledge tab takes three kinds of source, and an agent can have any number of them. Publishing merges them into one docs tree, so a page from a later source replaces one at the same path.

| Source | Accepts | Limits |
|---|---|---|
| Upload | `.md`, `.markdown`, `.txt`, or a zip of them; a `.txt` file gets its name as the title | 20 MB per upload; a zip unpacks to at most 50 MB and 2,000 files; links, other file types and files that are not UTF-8 are skipped and listed |
| Git repository | one folder of a public repository over https, on its default branch or a named one | 20 MB of Markdown and text; 60 s; **Sync** fetches the folder again |
| Pasted text | a title and up to 200,000 characters | the title becomes the page's heading |

Each heading in a page starts a section, and a section is what an answer cites. A page needs text under its headings to become a section.

## Publish a version and keep the old one serving

Publishing builds a complete new version, then switches the agent to it in one step. The live version keeps answering while the new one builds, and open conversations finish on the version they started with. A version is a hash of the settings and the docs, so publishing the same content again gives the same version. VoiceCore keeps the last five. An agent can have at most 5,000 sections.

The build log lists sections that read like instructions to the assistant, such as "ignore all previous instructions". Those sections are kept but never quoted in an answer. **Turn off** stops new sessions for the agent at once; **Turn on** puts its last published version back.

## Settings an agent answers with

Settings take effect at the next Publish.

| Setting | What it does |
|---|---|
| Name | how the assistant names its docs |
| Docs URL | where the docs are published; answers link to the section they cite there. Empty: answers cite section titles without links |
| First message | said when someone opens the assistant |
| Instructions | added after VoiceCore's own rules (answer only from the docs, cite every fact), never instead of them |
| Voice | one of Deepgram's Aura-2 voices |
| Model | the language model, from the models VoiceCore has prices for |
| Key terms | words the speech recognizer should expect, such as product names. Leave out everyday words: a boosted common word gets heard where it wasn't said |
| Turn-taking | **Quick** (the default) answers after a short pause once the recognizer has a complete sentence. **Patient** waits for 0.8 s of silence, for people who pause mid-sentence; it never cut a question short in VoiceCore's endpoint study, and replies about 450 ms later |

## Allowed websites, API keys and spend

**Allowed websites** are the sites where your agents may answer. When someone opens the assistant, the voice server checks the address of the page it is on and refuses any site not on the list. Without this, anyone could copy your snippet onto their own site and spend your provider credit. Write one address per line, without a path:

- `docs.acme.com` allows that site;
- `https://www.acme.com` allows its secure pages only;
- `*.acme.com` allows every subdomain of acme.com.

The list applies to every agent on the install and takes effect within a second, with no restart. The console's own Test tab always works, so an empty list only matters once the snippet is on your site.

**API keys** are for scripts and CI: send `Authorization: Bearer vck_...` to the same API the console uses ([console API](../reference/console-api.md)). A key is shown once and stored only as a hash; revoking it takes effect at once.

**Spend** on Home is the provider spend recorded by the voice server's budget ledger, against its cap. The caps are in the install's `.env` (`VOICECORE_CAP_USD`, `VOICECORE_PUBLIC_TOTAL`, `VOICECORE_PUBLIC_DAILY`); when one is reached, voice stops and typed questions still get the closest section of the docs.

## The admin password

The installer generates the password and keeps it in the install's `.env` as `CONSOLE_ADMIN_PASSWORD`. To see it again, run this in the install folder:

```bash
npx create-voicecore info
```

To change it, edit `CONSOLE_ADMIN_PASSWORD` in `.env` (at least 12 characters) and run `docker compose up -d console`. The console takes the new password when it starts and signs everyone out.
