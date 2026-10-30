# VoiceCore docs site

A docs-only [Docusaurus](https://docusaurus.io) 3 site about building, measuring and tuning a real-time voice agent, using this repository as the worked example. The voice assistant (the widget in the bottom-right corner) answers from these pages only, and opens the page and section it cites.

```bash
pnpm --filter @voicecore/docs start    # http://localhost:3000, builds the widget first
pnpm --filter @voicecore/docs build    # static site in apps/docs/build
```

To talk to it, run the gateway and the orchestrator too (see `docs/getting-started/quickstart.md`).

## How the assistant uses these pages

- `voicecore/answer/ingest.py` reads every `docs/**/*.md` file and splits it at its `##` and `###` headings. Each section becomes one retrievable passage.
- A passage's URL is the page route plus the heading's anchor, exactly as Docusaurus builds it. For example, `docs/concepts/endpointing.md` → `/concepts/endpointing#eager-endpointing`.
- When an answer cites a passage, the widget asks the page to navigate there. `src/theme/Root.jsx` changes the route without a reload, scrolls to the heading and highlights that section.
- `harness/check_docs_anchors.py` builds the passage list and checks every URL against `build/`. A heading the site renders with a different anchor fails that check.

## Writing rules

These rules keep the assistant's citations precise.

**Front matter and headings**

- **Front matter** on every page: `title`, `description` (one sentence), `sidebar_label` if the title is long. Do not add `id` or `slug`, except `intro.md`, which has `slug: /`.
- **No `#` heading in the body.** Docusaurus renders `title` as the page's H1.
- **Use `##` and `###` only.** Each section must answer one thing on its own: 60–250 words, plus at most one code block or table. A reader landing on that section from the assistant must understand it without scrolling up.
- **Headings are specific phrases**, for example "Why eager endpointing merges early cut-offs", not "Details" or "Overview". They become the citation title. Keep them unique within a page.
- **Headings are plain words.** No links, code spans, emoji, or punctuation beyond hyphens, commas and question marks.

**Content**

- **Facts come from this repository:** code, `reports/`, `docs/adr/`, `docs/*.md`, `packages/protocol/SPEC.md`. Do not invent behaviour, flags, numbers or provider features.
- **Label every measured number** with its conditions: `live` or `mock`, n, p50 or p95. Example: "p50 841 ms (live, n = 15)".
- **Plain CommonMark.** Admonitions (`:::note`, `:::tip`, `:::warning`), fenced code with a language, tables, and relative links to other pages (`../concepts/latency.md`). No JSX, no MDX, no raw HTML.
- **Voice:** second person, present tense, short sentences, no marketing words.
