---
title: Use the dashboard
description: A plain-language tour of every page of the VoiceCore dashboard (the console) - Home, agents and their docs (from a website, files, text or Git), publishing, settings and turn-taking, testing, the snippet, the Voice page with keys and spending limits, allowed websites, API keys and the password.
---

## What the dashboard is for

The dashboard is where you run your VoiceCore install. You open it in a browser, at the address the installer printed, and sign in with its password. From there you give assistants their docs, put them live, and get the one line that adds the button to your website. In these docs it is also called the console.

New to VoiceCore? [Add VoiceCore to your website](../getting-started/install.md) walks through the whole setup, from an empty server to a working button.

## Home

**Home** shows four things at a glance:

| Tile | What it tells you |
|---|---|
| Agents live | How many assistants are answering right now |
| Spend | What voice has spent in total and today, against your limits. Opens the Voice page |
| Voice | On, once both provider keys are saved. Off means typed questions get text answers only |
| Allowed websites | The websites where your assistants may answer |

Below them is the list of your agents. An **agent** is one assistant: its docs, its settings and its live version. You can have several, for example one per product, each with its own button.

## An agent's page

Open an agent from **Agents**. Until it is live and on your site, the top of the page shows four steps, ticked as you finish each one: **Add docs**, **Publish**, **Test** and **Embed**. They disappear once all four are done. The page has four tabs, one per step.

## Add docs on the Knowledge tab

An agent can have as many sources of docs as you like. Pick one way at a time:

| Way | Takes | Limits |
|---|---|---|
| **Website** | The address of your help or docs pages, such as `https://yoursite.com/help/`. VoiceCore reads that page and every page linked below it on the same site, leaving out menus, headers and footers. Each page keeps its real address, so answers link to it | 200 pages, read within 60 s. Public `https` addresses only. Pages that need JavaScript to show their text can't be read. **Sync** reads the site again |
| **Upload files** | Markdown (`.md`, `.markdown`), text (`.txt`), or a `.zip` of a folder of them. A `.txt` file's name becomes its title | 20 MB per upload. A zip can unpack to 50 MB and 2,000 files. Other file types are skipped, and the dashboard lists what it skipped |
| **Paste text** | A title and some text, such as an FAQ | 200,000 characters |
| **Git repository** | One folder of a public repository, over `https` | 20 MB of files, fetched within 60 s. **Sync** fetches the folder again |

**The website becomes an allowed website.** Adding docs from a website also adds that site to [Allowed websites](#allowed-websites), with and without `www`, since that is where the button will go. The Knowledge tab says when it does.

**How docs become answers.** Every heading starts a section. When a visitor asks something, VoiceCore finds the sections that match and answers from them only, citing each one. A heading with no text under it doesn't become a section. If two sources have a page at the same path, the one added later wins.

Next to your sources, **Live version** shows what visitors get right now: how many sections, from how many pages, and when it was published.

## Publish

**Publish** puts your current docs and settings live. VoiceCore builds a complete new version first, showing its progress (such as "Embedding 120 of 342 sections"), then switches to it in one step. Until then, the old version keeps answering. Conversations already going finish on the version they started with.

- Publishing the same docs and settings again changes nothing.
- VoiceCore keeps the last five versions.
- One agent can hold up to 5,000 sections.
- If a section reads like an instruction to the assistant, such as "ignore all previous instructions", the build log says so. That section is never quoted in an answer.

**Turn off** stops new conversations with the agent at once. **Turn on** puts its last published version back.

## Settings

Change settings on the **Settings** tab, press **Save settings**, then **Publish** to put them live.

| Setting | What it does |
|---|---|
| Name | The assistant's name for your docs |
| Docs URL | Where uploaded or pasted docs live on your website, such as `https://yoursite.com/help/`. Answers then link to the section they used. Empty: answers name the section without a link. Docs read from a website always link to their own pages. A new Docs URL also adds its website to Allowed websites |
| First message | What the assistant says when someone opens it |
| Instructions | Extra rules, such as "Keep answers short". They come after VoiceCore's own rules (answer only from the docs, cite every fact) and can't replace them |
| Voice | Which of Deepgram's voices speaks |
| Model | The language model that writes the answers |
| Key terms | Names the speech recognizer should expect, such as your product names. Leave out everyday words: a boosted everyday word gets heard where nobody said it |
| Turn-taking | When the assistant decides you've finished speaking. See below |

**Quick or Patient turn-taking.** **Quick**, the default, answers after a short pause once the speech recognizer has a whole sentence. That is fast, but it can cut in when someone pauses mid-sentence to think. **Patient** waits for 0.8 s of silence. In VoiceCore's endpoint study it never cut a question short, and its answers started about 450 ms later. Choose Patient when people ask longer or more thoughtful questions.

## Test and Embed

The **Test** tab holds a page with exactly the line your website will use. Click the button in its corner, allow the microphone, and ask something. It always works here, even before you list any websites.

The **Embed** tab gives that line, with a **Copy snippet** button. Paste it before `</body>` on your pages. [Step 7 of the setup guide](../getting-started/install.md#step-7-put-the-button-on-your-website) shows where it goes for WordPress, Webflow, Next.js and other platforms.

## The Voice page: your provider keys

Voice uses two providers, paid from your own accounts: **Deepgram** hears the visitor and speaks the answer, and **OpenRouter** runs the language model. Paste a key for each and press **Save key**.

- VoiceCore checks each key with its provider right away, at no cost. A wrong key is refused on the spot, and nothing is saved.
- Once both keys are saved, the next conversation speaks and listens. No restart.
- A saved key is never shown again, only its last four characters.
- A key saved here replaces one set on the server, in `.env` or the environment. **Remove** brings the server's key back, if there is one.

Until both keys are there, visitors can still type questions, and they get the closest section of your docs as text, at no cost.

## Allowed websites

These are the websites where your assistants may answer. When someone opens the button, VoiceCore checks which website the page is on and refuses any site not on this list. Without it, anyone could copy your line onto their own site and spend your credit.

A website you read docs from, or set as an agent's Docs URL, is added for you. Remove it here if you don't want it; VoiceCore adds it again only if you read that website again or set a new Docs URL.

Write one address per line, without a path:

| You write | It allows |
|---|---|
| `docs.acme.com` | that site only (not `www.docs.acme.com`) |
| `https://www.acme.com` | that site, on secure pages only |
| `*.acme.com` | every subdomain of acme.com |

The list applies to every agent and takes effect within a second.

## API keys

API keys are for scripts, not people: a script can do anything the dashboard does by sending `Authorization: Bearer vck_...` to the [same API](../reference/console-api.md). Give each key a name that says what it's for. A key is shown once, when you create it. **Revoke** stops it working at once.

These are not your Deepgram or OpenRouter keys; those go on the Voice page.

## Spending limits

The **Voice** page also holds the spending limits. VoiceCore stops speaking once one is reached, and keeps answering typed questions with text from your docs, at no cost. Change them and press **Save limits**; they apply from the next conversation, with no restart.

| Limit | What it limits | Starts at |
|---|---|---:|
| Per day | voice spending in one day (from midnight UTC) | $1 |
| In total | voice spending since you installed it | $10 |

Under each limit, the page shows what has been spent so far. The **Spend** tile on Home shows the same. [What it costs](../getting-started/install.md#what-it-costs) explains what a question costs and how the limits work.

The starting values come from the install's `.env` file (`VOICECORE_PUBLIC_DAILY`, `VOICECORE_PUBLIC_TOTAL` and `VOICECORE_CAP_USD`). Limits saved on the Voice page take their place.

## The password

The installer made the password and keeps it in the install's `.env` file as `CONSOLE_ADMIN_PASSWORD`. To see it again, run this in the install folder:

```bash
npx create-voicecore info
```

To change it, edit `CONSOLE_ADMIN_PASSWORD` in `.env` (at least 12 characters) and run `docker compose up -d console`. The new password works at once, and everyone is signed out.
