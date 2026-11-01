---
title: Add VoiceCore to your website
sidebar_label: Add it to your website
description: A plain-language, step-by-step guide to putting a voice assistant on your website that answers from your own docs, from an empty server to a working button, including costs, spending limits and fixes for common problems.
---

## Copy a prompt for your AI agent

Using an AI assistant such as Claude Code, Cursor or ChatGPT? Copy this prompt into it with the button in the box's corner. It points the assistant at this guide; the assistant then walks you through each step, and can add the button to your website's code for you.

```prompt title="Prompt for your AI agent"
Help me add VoiceCore to my website. VoiceCore is a voice assistant that runs on my own server and answers visitors' questions from my own docs.

Follow this guide, one step at a time:
https://voicecore-docs.fly.dev/getting-started/install

How to help me:
- First ask what I already have: a Linux server, Deepgram and OpenRouter accounts, the address of my help or docs pages, and what my website is built with.
- For each step, tell me exactly what to run or click, wait until I say it is done, and check the result with me before the next step.
- At step 7, add the snippet from my VoiceCore dashboard to my website's code in this project, in the right place for its framework.
- Never ask me to paste passwords or API keys into this chat. I will type them into the VoiceCore dashboard myself.
```

## What you get at the end

A button in the corner of your website. A visitor clicks it and asks a question out loud, or types it. A spoken answer starts in about a second: [841 ms](../concepts/latency.md) is the median in VoiceCore's own measurements. Every answer comes from your own docs, and links to the page it used. If your docs don't cover the question, the assistant says so instead of making something up.

You run it yourself, on your own server, and manage it from your own dashboard: add docs, pick a voice, see what it has spent. Nobody else hosts it, and nothing is sent to this project.

## The whole setup in short

1. Rent a small Linux server.
2. Paste one line into it. It installs everything and prints your dashboard's address and password.
3. In the dashboard, paste your two provider keys.
4. Paste the address of your help pages and press **Publish**.
5. Copy one line into your website.

The steps below explain each one.

## What you need

| You need | What it is for | What it costs |
|---|---|---|
| A server | A computer that is always on and reachable from the internet. VoiceCore runs on it. Linux (Ubuntu works well), at least 1 GB of memory and 10 GB of disk. | A small one costs a few dollars a month. |
| A Deepgram account | Turns the visitor's speech into text, and the answer back into speech. | Pay for what you use. |
| An OpenRouter account | Runs the language model that writes each answer from your docs. | Pay for what you use; you add credit first. |
| Your docs | Your help pages, FAQ or product guides: their web address, or Markdown (`.md`) and text (`.txt`) files, or text you paste. | |

You don't need a domain name. VoiceCore gets a secure address from your server's own IP address. You can [switch to a name of your own](#use-a-web-address-of-your-own) whenever you like.

Just want to see it first, with no server? Install [Docker Desktop](https://docs.docker.com/get-docker/) and [Node.js](https://nodejs.org/), run `npx create-voicecore` on your own computer, and press Enter at its one question. You get the same dashboard at `http://localhost:8000`, and the assistant answers on its Test tab. A real website can't reach your computer, so come back to step 1 when you are ready.

## How the pieces fit together

1. Your website loads one small script from your VoiceCore server. The script adds the button.
2. When a visitor talks, their voice goes to your VoiceCore server, not to your website's server.
3. Your VoiceCore server sends the audio to Deepgram to get the words, finds the parts of your docs that match, asks the language model on OpenRouter to write an answer from those parts only, and sends the answer back to Deepgram to be spoken.
4. The visitor hears the answer and sees links to the pages it came from.

Your Deepgram and OpenRouter keys stay on your VoiceCore server. A visitor's browser never sees them. Audio is not stored.

## Step 1: Get a server

Rent a small Linux server, often called a VPS, from any hosting company: DigitalOcean, Hetzner, Linode, Vultr, AWS Lightsail and many others sell them. Pick Ubuntu, and at least 1 GB of memory.

The hosting company gives you two things:

- the server's **IP address**, a number like `203.0.113.10`;
- a way to **log in**, usually with `ssh` from your computer's terminal:

```bash
ssh root@203.0.113.10
```

Make sure the server accepts web traffic on **ports 80 and 443**. Most hosting companies have a firewall page in their control panel: allow HTTP (80) and HTTPS (443). If the server itself runs the Ubuntu firewall, also run `ufw allow 80,443/tcp`.

## Step 2: Install VoiceCore with one line

Logged in to the server, paste this line and press Enter:

```bash
curl -fsSL https://raw.githubusercontent.com/ai-calypse/voicecore-lab/main/install.sh | sudo sh
```

It installs what VoiceCore needs and then VoiceCore itself:

- **Docker** runs VoiceCore's parts in containers: sealed boxes that bring everything they need, so nothing else on the server changes.
- **Node.js** runs VoiceCore's installer.
- **VoiceCore** itself, a few hundred MB, with a secure (`https`) certificate for your server's address. Browsers only let a page use the microphone on a secure address.

It takes two or three minutes and finishes with:

```text
VoiceCore is running.

  Dashboard  https://203.0.113.10
  Password   q3Vx9LdT2pWn7KcR0bYa
  Voice      off: add your Deepgram and OpenRouter keys on the dashboard's Voice page
```

- **Save the password** in your password manager. It was made just for this install.
- Everything lives in a folder called `voicecore` in your home folder. Its `.env` file holds your settings and secrets, so keep it private.
- Lost the password? Run `cd ~/voicecore && npx create-voicecore info`. It shows the address and password again.

## Step 3: Sign in to your dashboard

Open the dashboard address in your browser and enter the password. **Home** shows four things: how many assistants are live, what has been spent, whether voice is on, and which websites may use your assistant.

In VoiceCore, one assistant is called an **agent**. You can have several, for example one per product.

## Step 4: Turn on voice with your two keys

A key is a long password that lets VoiceCore use your account at a provider. You need one from Deepgram and one from OpenRouter.

**Deepgram:**

1. Sign up at [console.deepgram.com](https://console.deepgram.com/).
2. Open **API Keys** and create a key. Copy it: Deepgram shows it only once.

**OpenRouter:**

1. Sign up at [openrouter.ai](https://openrouter.ai/).
2. Add some credit on its **Credits** page. A few dollars is enough to start.
3. Open **Keys** and create a key. Give it a **credit limit**: the key can then never spend more than that, whatever happens. Copy the key.

In your dashboard, open **Voice**, paste each key and press **Save key**. VoiceCore checks each key with its provider right away, at no cost:

- "Saved. Deepgram accepted the key." means it worked.
- "Deepgram did not accept this key" means the key was copied wrong or deleted. Copy it again.

Once both keys are saved, the page says **Voice is on**, and the next conversation speaks and listens. No restart needed. A saved key is never shown again, only its last four characters.

The same page holds your [spending limits](#the-spending-limits). They start at $1 a day and $10 in total.

## Step 5: Give the assistant your docs

1. Open **Agents** and press **New agent**. Give it a name, such as "Help center".
2. On its **Knowledge** tab, **Website** is already chosen. Paste the address of your help or docs pages, such as `https://yoursite.com/help/`, and press **Read website**.

VoiceCore reads that page and every page linked below it on the same site, such as `https://yoursite.com/help/billing`, up to 200 pages. It takes up to a minute. It leaves out menus, headers and footers, and keeps each page's real address, so answers link straight to the page they used. Your website is also added to **Allowed websites** for you: that is where the button will go.

Docs somewhere else? There are three other ways:

| Way | Good for | Limits |
|---|---|---|
| **Upload files** | Markdown (`.md`, `.markdown`), text (`.txt`), or a `.zip` of a whole folder of them | 20 MB per upload |
| **Paste text** | An FAQ or a short note: a title and the text | 200,000 characters |
| **Git repository** | Docs kept in a public GitHub (or other https) repository: its address and the folder | 20 MB of files |

**How the assistant reads your docs.** Every heading starts a section. When someone asks a question, VoiceCore finds the sections that match and answers from them only. Clear headings give better answers, so write them the way a visitor would ask: "How refunds work" works better than "Policy 4.2". A heading with no text under it is skipped.

**What it can't read yet.** PDFs, Word files, and websites that need JavaScript to show their text (the **Website** way then says it found no readable text). Copy their text into **Paste text**, or save it as a `.txt` file.

Changed your help pages? Press **Sync** next to the website on the Knowledge tab, then **Publish**.

## Step 6: Publish and test

Press **Publish**. VoiceCore splits your docs into sections and prepares each one for searching. You see the progress, such as "Embedding 12 of 40 sections". When it is done, the agent shows **Live**.

Open the **Test** tab. It holds the same button your website will get. Click it, allow the microphone, and ask a question your docs answer. Then try one they don't: the assistant should say it can't find that.

Want to change how it sounds or behaves? The **Settings** tab has these, all optional. Press **Save settings**, then **Publish** again:

| Setting | What it does |
|---|---|
| Docs URL | Where uploaded or pasted docs live on your website, such as `https://yoursite.com/help/`, so their answers link to the right page. Not needed for docs read from a website. Setting it also adds that website to **Allowed websites**. |
| First message | What the assistant says when someone opens it, such as "Hi! Ask me anything about our product." |
| Instructions | Extra rules, such as "Keep answers short". They come after VoiceCore's own rules (answer only from your docs, cite every fact) and can't replace them. |
| Voice | Which voice speaks the answers. |
| Model | The language model that writes the answers. The default is fast and cheap; keep it unless you have a reason to change. |
| Key terms | Product or brand names the speech recognizer should expect, such as "Acme" or "SnapSync". Leave out everyday words. |
| Turn-taking | **Quick** answers after a short pause. **Patient** waits for 0.8 s of silence, for people who pause in the middle of a sentence. |

Changed your docs or settings later? Press **Publish** again. Conversations already going finish on the old version, and new ones get the new one.

## Step 7: Put the button on your website

Open your agent's **Embed** tab and press **Copy snippet**. It is one line, like this:

```html
<script src="https://203.0.113.10/widget.js" data-agent="help-center" async></script>
```

Paste it just before `</body>`, on every page where the button should appear. Most sites have one shared footer or layout, so you paste it once.

| Your website is built with | Where the line goes |
|---|---|
| Plain HTML | Before `</body>` in each page, or in the shared footer |
| WordPress | A "header and footer code" plugin, such as WPCode, in its footer box |
| Webflow | Site settings, Custom code, Footer code |
| Squarespace | Settings, Advanced, Code injection, Footer (paid plans) |
| Shopify | Online Store, Themes, Edit code, `theme.liquid`, before `</body>` |
| React (Vite) | `index.html`, before `</body>` |
| Next.js | The root layout, with the `Script` component (below) |
| Docusaurus | `scripts` in `docusaurus.config.js` (below) |

Menu names can change a little over time. In Next.js, the root layout gets:

```tsx
import Script from "next/script";

<Script src="https://203.0.113.10/widget.js" data-agent="help-center" strategy="afterInteractive" />
```

In Docusaurus, `docusaurus.config.js` gets:

```js
scripts: [{ src: "https://203.0.113.10/widget.js", async: true, "data-agent": "help-center" }],
```

**Optional extras.** Add these to the same line:

| Add | What it does |
|---|---|
| `data-position="left"` | Puts the button in the bottom-left corner, for a page that already has a chat button on the right |
| `data-title="Ask us"` | The words on the button |
| `data-name="Acme help"` | The title at the top of the open panel |

The [widget page](./embed-the-widget.md) lists every option. If your website sends a Content-Security-Policy header (if you don't know, it probably doesn't), allow your VoiceCore address in it, both `https://` and `wss://`.

**Allowed websites.** The button only starts a conversation on a website listed under **Allowed websites** in the dashboard. That stops anyone else from copying your button onto their own site and spending your credit. A website you read docs from, or set as a Docs URL, is added for you, with and without `www`. Putting the button on another website? Add it there, one address per line, without `https://` or a path. `*.yoursite.com` allows every subdomain.

## Step 8: Check it on your website

Open your website on its `https` address. The button sits in the bottom-right corner, or the bottom-left with `data-position="left"`. Click it, allow the microphone, and ask a question. It works on phones too.

That's it: your website has a voice assistant.

## Use a web address of your own

The address from step 2 is your server's IP address. It works, but it changes if you ever move to a new server, and then the snippet on your website has to change too. An address like `voice.yoursite.com` stays the same. To switch:

1. Where you manage your domain's DNS (the company you bought the domain from, or Cloudflare), add one record. If you use Cloudflare, set it to **DNS only** (the grey cloud), so VoiceCore can get its own certificate.

| Type | Name | Value |
|---|---|---|
| `A` | `voice` | your server's IP address, for example `203.0.113.10` |

2. Wait until `ping voice.yoursite.com` shows your server's IP address. It can take a few minutes.
3. On the server, run the install line again, with your address at the end:

```bash
curl -fsSL https://raw.githubusercontent.com/ai-calypse/voicecore-lab/main/install.sh | sudo sh -s -- --domain voice.yoursite.com
```

Your agents, docs, keys and password stay. Copy the snippet from the **Embed** tab again: it now uses the new address.

## What it costs

VoiceCore itself is free. You pay your server's hosting company, and Deepgram and OpenRouter for what visitors use.

One spoken question costs about **1 US cent**. That is an estimate from the providers' list prices, not a measurement of your site:

| Part | Price | One question |
|---|---|---:|
| Listening (Deepgram) | $0.0077 per minute while the microphone is on | about $0.004 for 30 seconds |
| Speaking the answer (Deepgram) | $0.030 per 1,000 characters | about $0.006 for a 200-character answer |
| Writing the answer (OpenRouter) | depends on the model | about $0.0006 with the default model (measured median, 29 live answers) |
| **Total** | | **about $0.01** |

## The spending limits

To protect you from a surprise bill, VoiceCore stops speaking once it reaches a limit. After that it still answers typed questions, at no cost, with the closest section of your docs. Set the limits on the dashboard's **Voice** page, under **Spending limits**. They apply from the next conversation:

| Limit | What it limits | Starts at |
|---|---|---:|
| Per day | what voice can spend in one day (the day starts at midnight UTC) | $1 |
| In total | what voice can spend in total, since you installed it | $10 |

At about 1 cent a question, $1 is roughly 100 questions a day, and $10 roughly 1,000 in total. There is one more effect: while a conversation runs, VoiceCore sets aside up to $0.18 for it, the most one conversation could cost, and gives back what wasn't used when it ends. So $1 a day also means about five conversations can talk at the same time. A busy website needs higher limits: raise them as you learn what your visitors use.

The **Voice** page and **Home** show what has been spent today and in total. The credit limit on your OpenRouter key and usage alerts at Deepgram are a second safety net.

## Keep it running

VoiceCore starts again by itself when the server restarts. Run these in the `voicecore` folder (`cd ~/voicecore`):

| To | Run |
|---|---|
| See the dashboard address and password | `npx create-voicecore info` |
| Update to the newest version (your agents, docs and settings stay) | `npx create-voicecore@latest upgrade` |
| Change the dashboard password | Edit `CONSOLE_ADMIN_PASSWORD` in `.env` (at least 12 characters), then `docker compose up -d console` |
| Stop it (your data stays) | `npx create-voicecore uninstall` |
| Start it again | `docker compose up -d` |
| Remove it and all its data | `npx create-voicecore uninstall --delete-data` |

## If something doesn't work

| What you see | Why | What to do |
|---|---|---|
| "run it as root" | The line needs administrator rights | Keep `sudo` in the line, or log in as `root` |
| The installer says the address "doesn't answer yet" | Ports 80 and 443 are closed, or your own domain doesn't point at the server yet | Open the ports (step 1's firewall). With your own domain, check it with `ping`. VoiceCore keeps trying to get its certificate, so it starts working a few minutes after the fix |
| "Deepgram did not accept this key" | The key was copied wrong, or deleted at Deepgram | Copy it again from the provider |
| Home says voice is off | One of the two keys is missing | Open **Voice** and add it |
| "No readable text at" your address | The site builds its pages with JavaScript, or the address has no text | Try the address of one help page, or upload the docs as files |
| The button doesn't appear on your site | The line isn't on the page, or your site's Content-Security-Policy blocks it | View the page's source and look for `widget.js`; see step 7 |
| The button opens, then says "Could not connect: token request failed (403)" | Your website isn't on the list | Add it under **Allowed websites**, with and without `www` |
| The microphone doesn't work | The page isn't on `https`, or the browser blocked the microphone | Use the `https` address, and allow the microphone in the browser's site settings. Typing still works |
| Answers come as text only, saying the budget is used up | A spending limit was reached | Raise it on the **Voice** page |
| The assistant says your docs don't cover something they do | The section isn't there, or its heading has no text under it | Check the Knowledge tab, add or fix the docs, and **Publish** again |
| Your words get cut off when you pause | Turn-taking is set to Quick | Set **Patient** on the Settings tab, then **Publish** |

Still stuck? The [troubleshooting guide](../guides/troubleshooting.md) goes deeper, and the [dashboard guide](../guides/console.md) explains every page.
