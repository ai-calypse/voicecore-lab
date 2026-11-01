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
- First ask what I already have: a server, a domain name, Deepgram and OpenRouter accounts, and what my website is built with.
- For each step, tell me exactly what to run or click, wait until I say it is done, and check the result with me before the next step.
- At step 10, add the snippet from my VoiceCore dashboard to my website's code in this project, in the right place for its framework.
- Never ask me to paste passwords or API keys into this chat. I will type them into the VoiceCore dashboard myself.
```

## What you get at the end

A button in the corner of your website. A visitor clicks it and asks a question out loud, or types it. A spoken answer starts in about a second: [841 ms](../concepts/latency.md) is the median in VoiceCore's own measurements. Every answer comes from your own docs, and links to the part it used. If your docs don't cover the question, the assistant says so instead of making something up.

You run it yourself, on your own server, and manage it from your own dashboard: add docs, pick a voice, see what it has spent. Nobody else hosts it, and nothing is sent to this project.

## What you need

| You need | What it is for | What it costs |
|---|---|---|
| A server | A computer that is always on and reachable from the internet. VoiceCore runs on it. Linux (Ubuntu works well), at least 1 GB of memory and 10 GB of disk. | A small one costs a few dollars a month. |
| A web address for VoiceCore | For example `voice.yoursite.com`. Browsers only let a web page use the microphone over a secure (`https`) address, so VoiceCore needs a name, not just a number. | Free if you already own `yoursite.com`. |
| A Deepgram account | Turns the visitor's speech into text, and the answer back into speech. | Pay for what you use. |
| An OpenRouter account | Runs the language model that writes each answer from your docs. | Pay for what you use; you add credit first. |
| Your docs | Help pages, an FAQ, product guides: Markdown files (`.md`), text files (`.txt`), or text you paste. | |

Just want to see it first, with no server? Run `npx create-voicecore` on your own computer and press Enter at its one question. You get the same dashboard at `http://localhost:8000`, and the assistant answers on its Test tab. A real website can't reach your computer, so come back to step 1 when you are ready.

## How the pieces fit together

1. Your website loads one small script from your VoiceCore server. The script adds the button.
2. When a visitor talks, their voice goes to your VoiceCore server, not to your website's server.
3. Your VoiceCore server sends the audio to Deepgram to get the words, finds the parts of your docs that match, asks the language model on OpenRouter to write an answer from those parts only, and sends the answer back to Deepgram to be spoken.
4. The visitor hears the answer and sees links to the docs it came from.

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

## Step 2: Point a web address at the server

Choose an address for VoiceCore, such as `voice.yoursite.com`. Where you manage your domain's DNS (the company you bought the domain from, or Cloudflare), add one record:

| Type | Name | Value |
|---|---|---|
| `A` | `voice` | your server's IP address, for example `203.0.113.10` |

It can take a few minutes to start working. To check, run `ping voice.yoursite.com`: it should show your server's IP address. If you use Cloudflare, set the record to **DNS only** (the grey cloud), so VoiceCore can get its own secure certificate.

## Step 3: Install Docker and Node.js on the server

Logged in to the server, run:

```bash
curl -fsSL https://get.docker.com | sh
curl -fsSL https://deb.nodesource.com/setup_lts.x | bash -
apt-get install -y nodejs
```

- **Docker** runs VoiceCore's parts in containers: sealed boxes that bring everything they need, so nothing else on the server changes.
- **Node.js** runs VoiceCore's one-line installer.

To check, run `docker --version` and `node --version`. Node.js must be version 20 or newer.

## Step 4: Install VoiceCore

On the server, run:

```bash
npx create-voicecore
```

If it asks `Ok to proceed?`, type `y`. Then it asks one question:

```text
Public domain for VoiceCore, e.g. voice.example.com (Enter: this machine only):
```

Type the address from step 2, such as `voice.yoursite.com`, and press Enter.

The installer downloads VoiceCore (a few hundred MB), starts it, and gets a secure certificate for your address. It finishes with:

```text
VoiceCore is running.

  Dashboard  https://voice.yoursite.com
  Password   q3Vx9LdT2pWn7KcR0bYa
  Voice      off: add your Deepgram and OpenRouter keys on the dashboard's Voice page
```

- **Save the password** in your password manager. It was made just for this install.
- Everything lives in a new folder called `voicecore`. Its `.env` file holds your settings and secrets, so keep it private.
- Lost the password? In that folder, run `npx create-voicecore info`. It shows the address and password again.

## Step 5: Sign in to your dashboard

Open the dashboard address in your browser and enter the password. **Home** shows four things: how many assistants are live, what has been spent, whether voice is on, and which websites may use your assistant.

In VoiceCore, one assistant is called an **agent**. You can have several, for example one per product.

## Step 6: Turn on voice with your two keys

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

## Step 7: Give the assistant your docs

1. Open **Agents** and press **New agent**. Give it a name, such as "Help center".
2. On its **Knowledge** tab, add your docs in one of three ways:

| Way | Good for | Limits |
|---|---|---|
| **Upload files** | Markdown (`.md`, `.markdown`), text (`.txt`), or a `.zip` of a whole folder of them | 20 MB per upload |
| **Paste text** | An FAQ or a short note: a title and the text | 200,000 characters |
| **Git repository** | Docs kept in a public GitHub (or other https) repository: its address and the folder | 20 MB of files |

**How the assistant reads your docs.** Every heading starts a section. When someone asks a question, VoiceCore finds the sections that match and answers from them only. Clear headings give better answers, so write them the way a visitor would ask: "How refunds work" works better than "Policy 4.2". A heading with no text under it is skipped.

**What it can't read yet.** PDFs, Word files and other websites. Copy their text into **Paste text**, or save it as a `.txt` file.

3. On the **Settings** tab, fill in what you need and press **Save settings**:

| Setting | What it does |
|---|---|
| Docs URL | Where these docs live on your website, such as `https://yoursite.com/help/`. Answers then link to the right page: with this URL, `refunds.md` links to `https://yoursite.com/help/refunds`. Leave it empty to show section titles without links. |
| First message | What the assistant says when someone opens it, such as "Hi! Ask me anything about our product." |
| Instructions | Extra rules, such as "Keep answers short". They come after VoiceCore's own rules (answer only from your docs, cite every fact) and can't replace them. |
| Voice | Which voice speaks the answers. |
| Model | The language model that writes the answers. The default is fast and cheap; keep it unless you have a reason to change. |
| Key terms | Product or brand names the speech recognizer should expect, such as "Acme" or "SnapSync". Leave out everyday words. |
| Turn-taking | **Quick** answers after a short pause. **Patient** waits for 0.8 s of silence, for people who pause in the middle of a sentence. |

## Step 8: Publish and test

Press **Publish**. VoiceCore splits your docs into sections and prepares each one for searching. You see the progress, such as "Embedding 12 of 40 sections". When it is done, the agent shows **Live**.

Open the **Test** tab. It holds the same button your website will get. Click it, allow the microphone, and ask a question your docs answer. Then try one they don't: the assistant should say it can't find that.

Changed your docs or settings later? Press **Publish** again. Conversations already going finish on the old version, and new ones get the new one.

## Step 9: Allow your website

Open **Allowed websites** and write your website's address, one per line, without `https://` or a path:

```text
yoursite.com
www.yoursite.com
```

This stops anyone else from copying your button onto their own site and spending your credit. Add both `yoursite.com` and `www.yoursite.com` if your site opens on both. `*.yoursite.com` allows every subdomain. Press **Save websites**; it takes effect within a second.

## Step 10: Put the button on your website

Open your agent's **Embed** tab and press **Copy snippet**. It is one line, like this:

```html
<script src="https://voice.yoursite.com/widget.js" data-agent="help-center" async></script>
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

<Script src="https://voice.yoursite.com/widget.js" data-agent="help-center" strategy="afterInteractive" />
```

In Docusaurus, `docusaurus.config.js` gets:

```js
scripts: [{ src: "https://voice.yoursite.com/widget.js", async: true, "data-agent": "help-center" }],
```

**Optional extras.** Add these to the same line:

| Add | What it does |
|---|---|
| `data-position="left"` | Puts the button in the bottom-left corner, for a page that already has a chat button on the right |
| `data-title="Ask us"` | The words on the button |
| `data-name="Acme help"` | The title at the top of the open panel |

The [widget page](./embed-the-widget.md) lists every option. If your website sends a Content-Security-Policy header (if you don't know, it probably doesn't), allow `https://voice.yoursite.com` and `wss://voice.yoursite.com` in it.

## Step 11: Check it on your website

Open your website on its `https` address. The button sits in the bottom-right corner, or the bottom-left with `data-position="left"`. Click it, allow the microphone, and ask a question. It works on phones too.

That's it: your website has a voice assistant.

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

To protect you from a surprise bill, VoiceCore stops speaking once it reaches a limit. After that it still answers typed questions, at no cost, with the closest section of your docs. The limits start low on purpose:

| Setting in `.env` | What it limits | Starts at |
|---|---|---:|
| `VOICECORE_PUBLIC_DAILY` | what voice can spend in one day (the day starts at midnight UTC) | $0.50 |
| `VOICECORE_PUBLIC_TOTAL` | what voice can spend in total, since you installed it | $2.00 |
| `VOICECORE_CAP_USD` | everything VoiceCore can spend in total | $5.00 |

At about 1 cent a question, $0.50 is roughly 50 questions a day. There is one more effect: while a conversation runs, VoiceCore sets aside up to $0.18 for it, the most one conversation could cost, and gives back what wasn't used when it ends. So $0.50 a day also means about two conversations can talk at the same time. A real website usually needs more. To raise the limits, on the server:

```bash
cd voicecore
nano .env          # change the three numbers, for example 3, 100 and 120
docker compose up -d
```

Keep `VOICECORE_PUBLIC_TOTAL` at or below `VOICECORE_CAP_USD`. **Home** in the dashboard shows what has been spent today and in total. The credit limit on your OpenRouter key and usage alerts at Deepgram are a second safety net.

## Keep it running

VoiceCore starts again by itself when the server restarts. Run these in the `voicecore` folder:

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
| The installer says Docker is not installed, or not running | Step 3 didn't finish | Run step 3 again, or start Docker with `systemctl start docker` |
| The dashboard address doesn't open | The web address doesn't point at the server yet, or ports 80 and 443 are closed | Check step 2 with `ping`, and step 1's firewall. VoiceCore keeps trying to get its certificate, so it starts working a few minutes after the fix |
| "Deepgram did not accept this key" | The key was copied wrong, or deleted at Deepgram | Copy it again from the provider |
| Home says voice is off | One of the two keys is missing | Open **Voice** and add it |
| The button doesn't appear on your site | The line isn't on the page, or your site's Content-Security-Policy blocks it | View the page's source and look for `widget.js`; see step 10 |
| The button opens, then says "Could not connect: token request failed (403)" | Your website isn't on the list | Add it under **Allowed websites**, with and without `www` (step 9) |
| The microphone doesn't work | The page isn't on `https`, or the browser blocked the microphone | Use the `https` address, and allow the microphone in the browser's site settings. Typing still works |
| Answers come as text only, saying the budget is used up | A spending limit was reached | Raise the limits (see above) |
| The assistant says your docs don't cover something they do | The section isn't there, or its heading has no text under it | Check the Knowledge tab, add or fix the docs, and **Publish** again |
| Your words get cut off when you pause | Turn-taking is set to Quick | Set **Patient** on the Settings tab, then **Publish** |

Still stuck? The [troubleshooting guide](../guides/troubleshooting.md) goes deeper, and the [dashboard guide](../guides/console.md) explains every page.
