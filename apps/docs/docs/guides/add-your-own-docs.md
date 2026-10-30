---
title: Add your own docs
description: Point the voice assistant at a Docusaurus site, write pages it can cite precisely, re-index after changes and check every citation link against the built site.
---

## What the assistant needs from a docs site

The voice assistant answers only from documentation it has indexed, and every answer cites the sections it used. To use your own docs, you give the orchestrator two things:

- **The Markdown source**: the `docs/` folder of a Docusaurus site. The orchestrator reads the files directly from disk. It does not crawl the website.
- **The site's URL**: where those docs are served. Ingest combines it with each file's route and each heading's anchor to build a citation URL.

At startup, ingest (`voicecore/answer/ingest.py`) splits every page at its `##` and `###` headings. Each section becomes one passage with its own URL. When an answer cites a passage, the widget asks the page to open that URL, and the page scrolls to the section.

For a citation to land in the right place, the URL that ingest computes must match the route and anchor that Docusaurus renders. This guide covers the flags, the route and anchor rules, the writing rules that keep citations precise, re-indexing, and the check that compares every passage URL with the built site.

## Point the orchestrator at your site

Two orchestrator flags select the docs:

- `--docs-dir`: the folder of Markdown pages. The default is `apps/docs/docs`, this site.
- `--docs-url`: the URL where those pages are served. The default is `http://localhost:3000/`, the local dev server of this site.

```bash
uv run python -m voicecore.server --providers live \
  --docs-dir path/to/your-site/docs \
  --docs-url https://docs.example.com/
```

Set `--docs-url` to the URL where the doc routes start, with a trailing slash. Docusaurus places doc routes under the site's `baseUrl` and the docs plugin's `routeBasePath`. This site uses `baseUrl: "/"` and `routeBasePath: "/"`, so its pages start at the site root. A site with the default `routeBasePath` serves its pages under `/docs/`, so its `--docs-url` must end in `/docs/`.

Without `--providers live`, the orchestrator uses mock providers, which return a canned answer. See [Configuration](../reference/configuration.md) for the other flags.

## Which files ingest reads

Ingest reads every file that matches `docs/**/*.md` under `--docs-dir`, in every subfolder. Each file is one page.

- **Only `.md` files are read.** A page written as `.mdx` is not indexed, so the assistant cannot cite it.
- **Front matter** is the `---` block at the top of the page. Ingest reads it as simple `key: value` lines, one key per line. Keep values on one line.
- **Headings** split the page into passages: each `##` and `###` heading starts a new section.
- **Code blocks** are skipped when looking for headings. A `# comment` line inside a fenced bash block is not a heading.

Ingest does not run Docusaurus. It does not see the sidebar, generated index pages, plugins or anything a theme adds to the page. It sees the Markdown you wrote, and it predicts the route and anchor that Docusaurus will give each section. That prediction is why the rules for routes and anchors below matter, and why the anchor check exists.

## How a page route is built

Ingest builds each page's route from its file path, the same way Docusaurus does by default: the base URL plus the path under `--docs-dir`, without `.md`.

| File under docs | Route with the default base URL |
|---|---|
| `concepts/endpointing.md` | `http://localhost:3000/concepts/endpointing` |
| `guides/add-your-own-docs.md` | `http://localhost:3000/guides/add-your-own-docs` |
| `guides/index.md` | the `guides` folder's route |
| `intro.md` with `slug: /` | `http://localhost:3000/` |

Two rules adjust the path:

- **`index.md` takes its folder's route.** The file name disappears from the URL.
- **A `slug` in front matter replaces the route.** This site uses that only for `intro.md`, which has `slug: /` and becomes the home page.

Docusaurus can also change a route in ways ingest does not follow from the file path. An `id` in front matter renames the page's route, and a number prefix such as `01-` in a file name is removed from the route by default. Avoid both. If a route still differs, the anchor check reports it.

## How section anchors are made

A section's anchor is the slug of its heading text, made the way Docusaurus 3 makes heading ids: with the github-slugger library (version 1.5.0 in this repository). Ingest uses the same rules:

- Letters are lowercased. Accented and other non-ASCII letters are kept.
- Punctuation and symbols are removed, except hyphens and underscores.
- Every space becomes one hyphen. Spaces are not collapsed, so two spaces give two hyphens.
- A heading text that repeats on a page gets `-1`, `-2` and so on.

| Heading | Anchor |
|---|---|
| Why eager endpointing merges early cut-offs | `why-eager-endpointing-merges-early-cut-offs` |
| What is barge-in, and why? | `what-is-barge-in-and-why` |
| Version 0.13.6 notes | `version-0136-notes` |
| Grounding rule - only cited sentences | `grounding-rule---only-cited-sentences` |

Other site generators use different rules. The uv docs used in the evals are built with MkDocs, whose Python-Markdown anchors fold letters to ASCII and collapse runs of hyphens. That is why ingest must match the generator your site uses.

## What one documentation section should contain

The assistant retrieves sections, not pages. A section is the unit it ranks, quotes to the model and cites. Write each `##` or `###` section so it answers one thing on its own:

- **60 to 250 words**, plus at most one code block or table.
- **Self-contained.** A reader who lands on the section from a citation, with no context, must understand it without scrolling up. Name the component, the setting or the event again instead of writing "as above".
- **One topic.** A section that mixes two topics ranks lower for both and gives the model half an answer.

Size has a mechanical reason too. In the current engine only the first 1,200 characters of a passage are quoted to the model, and only the first 2,000 characters are embedded for dense search. Text after that is invisible to the model. A short, focused section is quoted whole.

These rules come from the site's `apps/docs/README.md`, which lists every writing rule for this site.

## How to write headings that cite well

A heading becomes the section's citation title and its anchor. Write it for both:

- **Use a specific phrase**, for example "Why eager endpointing merges early cut-offs", not "Details" or "Overview". A specific heading tells the listener what the cited section is about, and it also gives keyword search good terms, because the title is indexed with the text.
- **Keep headings unique within a page.** A repeated heading gets an anchor with a `-1` suffix, and two sections with the same title are hard to tell apart in a citation.
- **Use plain words.** No links, code spans or emoji, and no punctuation beyond hyphens, commas and question marks. Other punctuation is dropped from the anchor or turns into extra hyphens, which makes anchors fragile.
- **Use `##` and `###` only.** They are the split points. Do not put a `#` heading in the body; Docusaurus renders the front matter `title` as the page's H1.

## Front matter every page needs

Every page starts with a front matter block:

```yaml
---
title: Barge-in and echo
description: How the agent stops talking the moment you interrupt it.
sidebar_label: Barge-in
---
```

- **`title`** is required. Docusaurus renders it as the page heading.
- **`description`** is one sentence that says what the page covers.
- **`sidebar_label`** is a shorter name for the sidebar. Add it only if the title is long.
- **Do not add `id` or `slug`.** Both change the page's route. The one exception on this site is `intro.md`, which has `slug: /` so that it becomes the home page.

Keep each value on a single line. Ingest reads front matter as simple `key: value` lines and does not parse YAML lists or values that span several lines.

## What content belongs on a page

The assistant repeats what your pages say, so the pages have to be right and complete on their own terms:

- **Facts come from the repository.** On this site that means code, `reports/`, `docs/adr/`, `docs/*.md` and `packages/protocol/SPEC.md`. Do not invent behaviour, flags, numbers or provider features. The assistant cannot tell an invented fact from a real one.
- **Label every measured number** with its conditions: `live` or `mock`, n, and p50 or p95. For example: "p50 841 ms (live, n = 15)". The assistant quotes numbers as written, so an unlabelled number gets repeated without its conditions.
- **Use plain CommonMark.** Admonitions (`:::note`, `:::tip`, `:::warning`), fenced code with a language, tables, and relative links to other pages are fine. No JSX, MDX or raw HTML.
- **Write in second person and present tense**, in short sentences, with no marketing words.

Short sentences also help in speech: the assistant answers in two or three short spoken sentences, and source text in that style is easier to summarise faithfully.

## Wording that stops a section from being quoted

Ingest checks every section with a regular expression for instruction-like text, as a defence against prompt injection. A section that matches is flagged as suspicious. It stays in the index, but the engine never quotes it to the model, so the assistant can never cite it.

The pattern looks for phrases that tell a model to drop its earlier instructions, give it a new role, ask for its hidden prompt, or mention credentials such as access keys. Ordinary documentation can trip it by accident. A setup page that names a provider credential in plain words, or a security page that quotes an attack, is a typical case.

If the assistant never cites a section you expect it to, check its wording first. Rephrase the matching phrase, for example by naming the environment variable instead of describing the credential in words. The defence and its eval results are explained in [Grounded answers](../concepts/grounded-answers.md).

## Re-index after you change the docs

The orchestrator builds its index once, at startup: ingest reads the pages, an in-memory SQLite FTS5 table is filled, and the dense vectors are loaded or computed. Edits to the Markdown files do not reach a running orchestrator. Restart it after you change the docs.

The dense vectors are cached under `.cache` at the repository root:

- **Vectors**: `.cache/answer_vectors_<hash>.npy`. The hash covers the content hash of every passage, so any edit to any section gives a new hash and re-embeds the whole corpus. A code comment puts that at about 20 s on CPU for about 1,000 passages. Restarting with unchanged docs loads the cached file instead.
- **Model files**: `.cache/fastembed` holds the `BAAI/bge-small-en-v1.5` model, downloaded on first use.

Old vector files are not deleted when the docs change. You can remove `.cache/answer_vectors_*.npy` at any time to reclaim space; the next start rebuilds the current one.

## Check every citation link against the built site

A citation is only as good as its link. `harness/check_docs_anchors.py` builds the same passage list that the orchestrator uses and checks every passage URL against the static site in `apps/docs/build`: the page must exist and must contain the anchor. A heading that Docusaurus renders with a different anchor than ingest predicts fails the check.

Build the site first, then run the check:

```bash
pnpm --filter @voicecore/docs build
uv run python harness/check_docs_anchors.py
```

Run it after you add a page, rename a heading, move a file or change a `slug`. Those are the edits that can break a route or an anchor. The check catches the problem before a user gets a citation that opens the top of a page instead of the cited section, or a page that does not exist.

## How the widget opens a cited section on your site

When an answer cites a section, the orchestrator sends `answer.sources` with each cited passage's URL. The widget then asks the host page to open that URL by dispatching a `voicecore:navigate` event.

On this docs site, `src/theme/Root.jsx` handles the event. It changes the route without reloading the page, scrolls to the cited heading and highlights that section. Because the page does not reload, the voice session keeps running while the page changes.

If you embed the widget in your own Docusaurus site, your site needs its own handler for `voicecore:navigate` to get the same behaviour. You can model it on this site's `Root.jsx`. How to add the widget to a page is in [Embed the widget](../getting-started/embed-the-widget.md).

## Why a citation opens the wrong place

When a citation opens the top of a page, the wrong page or nothing at all, the passage URL does not match the built site. The usual causes:

| Symptom | Likely cause | Fix |
|---|---|---|
| Opens the page but not the section | heading renamed after the orchestrator started | restart the orchestrator |
| Opens the page but not the section | heading with punctuation, code or links | rewrite it in plain words |
| Page not found | `--docs-url` missing the base path, for example `/docs/` | set it to where doc routes start |
| Page not found | number prefix in the file name, or an `id` in front matter | rename the file, remove `id` |
| Never cited at all | page is `.mdx`, or the section is flagged as suspicious | use `.md`, reword the section |

Run `harness/check_docs_anchors.py` against a fresh build to find every mismatch at once. More fixes are in [Troubleshooting](../guides/troubleshooting.md).
