---
title: Grounded answers
description: How the assistant retrieves documentation sections, releases only sentences that cite them, refuses when the docs do not cover a question, and resists instructions hidden in pages.
---

## What a grounded answer is

A grounded answer only states what a retrieved documentation passage says, and every factual sentence points to that passage. You can open the cited section and check the claim yourself.

VoiceCore builds each answer in four steps (`voicecore/answer/engine.py`):

1. **Retrieve.** Hybrid search over the indexed docs picks the 5 best passages. This runs locally and takes a few milliseconds.
2. **Prompt.** The LLM gets the question and the numbered passages, and must cite them as `[1]`, `[2]` and so on.
3. **Filter.** The `Grounding` filter releases the answer sentence by sentence, and only sentences backed by a valid citation.
4. **Cite.** One `answer.sources` event lists the cited passages, with titles and URLs taken from the index.

Retrieval runs before the LLM call, not as a tool the model calls. A turn therefore costs one LLM round trip instead of two. The same engine serves typed and spoken questions; for speech, the citation markers are removed before TTS.

## How the docs are split into passages

The index does not store whole pages. It stores sections. On this site, ingest (`voicecore/answer/ingest.py`) reads every Markdown page and splits it at its `##` and `###` headings. Each section becomes one passage with:

- **A canonical URL**: the page route plus the heading's anchor, exactly as the docs site renders it. A citation therefore opens the exact section, not just the page.
- **An id**: the first 12 hex characters of the SHA-256 of the URL. Ingesting the same docs twice gives the same ids.
- **A title** for citations: the page title and the heading, joined by " > ".
- **A content hash** of the section text, which keys the embedding cache.
- **A suspicious flag** for instruction-like text, used by the injection defences.

The answer quality numbers on this page come from a different corpus: the uv docs at tag 0.13.6, built with MkDocs, which gave 524 passages. How routes and anchors are computed for a Docusaurus site is in [Add your own docs](../guides/add-your-own-docs.md).

## Keyword search with SQLite FTS5 and BM25

The lexical half of retrieval uses an in-memory SQLite FTS5 table with two columns, the passage title and its text, and the `porter unicode61` tokenizer. Results are ranked by FTS5's built-in BM25.

The query is built from the question in `fts_query`:

- The question is reduced to its words, and each word is put in quotes. FTS5 operators and punctuation in user text (`.`, `--`, `*`, `:`) therefore cannot change the query.
- Words are joined with OR.
- Common question words and stopwords ("how", "do", "my", "the" and others) are dropped. In an OR query they only add noise to BM25.

Dropping question words was the one tuning step made on the dev questions. Before it, BM25 alone reached Recall@5 0.53 and MRR 0.345 on the uv docs; after it, 0.68 and 0.472 (offline, n = 19 dev questions). The lexical search returns its top 20 passages for fusion.

Neither half wins everywhere on its own. On the uv dev questions, dense search had the better Recall@1; on the holdout questions, BM25 did. That is why both are fused.

## Dense search with fastembed and bge-small

The semantic half of retrieval embeds every passage with `BAAI/bge-small-en-v1.5`, run locally through fastembed 0.9.1. It finds passages that say the same thing as the question in different words, which keyword search misses.

- **Passages.** The first 2,000 characters of each passage are embedded, in batches of 16. The default batch of 256 ran out of memory in a 2 GB container.
- **Similarity.** Vectors are normalised, so a dot product with the normalised query vector gives the cosine similarity.
- **Cache.** The vectors are saved under `.cache` at the repository root, keyed by a hash of every passage's content. Restarting with unchanged docs loads them instead of embedding again.
- **Event loop.** Embedding a query takes milliseconds of CPU, so the engine runs retrieval in a worker thread and keeps the session's event loop free for audio.

The dense search returns its top 20 passages, which are then fused with the BM25 ranking.

## How reciprocal rank fusion merges the two rankings

BM25 scores and cosine similarities are on different scales, so you cannot simply add them. Reciprocal rank fusion (RRF) uses only each passage's rank in each list:

```python
def rrf(rankings: list[list[str]], k: int = 60) -> list[str]:
    score: dict[str, float] = {}
    for ranking in rankings:
        for r, key in enumerate(ranking, 1):
            score[key] = score.get(key, 0.0) + 1 / (k + r)
    return sorted(score, key=lambda key: -score[key])
```

A passage gets `1 / (60 + rank)` from each list it appears in, with ranks starting at 1. A passage that both searches rank highly wins. A passage that only one search finds can still make the top 5. The constant k = 60 flattens the difference between neighbouring ranks, so neither search dominates.

The engine asks the fused ranking for 10 passages. It removes flagged and non-official ones, then keeps the best 5 for the prompt.

## Retrieval quality on the uv docs

Retrieval was measured offline, with no LLM, on the uv docs corpus (524 passages). A question counts as found when its answer key's `must_cite` section is in the top results (offline, n = 19 dev and n = 11 holdout questions).

| Split | Ranking | Recall@1 | Recall@5 | Recall@10 | MRR |
|---|---|---:|---:|---:|---:|
| dev | BM25 | 0.32 | 0.68 | 0.79 | 0.472 |
| dev | dense | 0.58 | 0.74 | 0.84 | 0.644 |
| dev | fused | 0.53 | 0.79 | 0.89 | 0.649 |
| holdout | BM25 | 0.55 | 0.82 | 1.00 | 0.692 |
| holdout | dense | 0.45 | 0.82 | 0.91 | 0.606 |
| holdout | fused | 0.82 | 1.00 | 1.00 | 0.886 |

Fusion gives the best Recall@5 and MRR on both splits. Recall@5 is what matters here, because the prompt quotes 5 passages. The holdout split was run only after the BM25 query change was chosen on dev. These are small samples: the numbers rank the variants, they are not production rates. Run it with `uv run python harness/retrieval_eval.py --split dev` or `--split holdout`.

## The Grounding rule for releasing sentences

The LLM's text is not sent to you as it streams. The `Grounding` class in `engine.py` splits it into sentences and decides, sentence by sentence, what may be released:

- **A sentence with a valid citation is released.** Valid means a number from 1 to the number of passages actually quoted.
- **A sentence without a valid citation is held.** It is released together with the next cited sentence of the same answer. Anything still uncited when the answer ends is dropped.
- **Invalid citation numbers are removed.** A `[7]` when only 5 passages were quoted cannot survive.
- **URLs written by the model are removed.** The model is told never to write URLs; any it writes anyway are cut out.
- **No valid citation at all means a refusal.** The whole answer is replaced with the refusal.

Releasing per sentence keeps latency low: TTS can start speaking the first grounded sentence while the model is still writing the second. The tests `test_citation_id_not_in_the_retrieved_set_is_rejected` and `test_urls_written_by_the_model_never_pass` cover the removal rules.

## Where citation URLs come from

The model never supplies a link. After the answer, the engine emits one `answer.sources` event with one entry per cited passage: `n`, `id`, `title` and `url`. All four come from the index, which built them from the docs files at ingest time.

So a citation cannot point to a page that was not retrieved, and it cannot point outside the docs. In the uv eval, citations to a passage that was not retrieved and URLs written by the model were 0. That is guaranteed by construction, because `Grounding` drops them before release.

The spoken version is cleaned for the voice. `speechify` removes the `[n]` markers, Markdown emphasis and code ticks, so TTS never reads "bracket two" aloud. The text version keeps the markers, so a reader can match each sentence to its source. A typed question and the same question spoken produce the same citations; `test_same_question_as_text_and_as_voice_gives_the_same_citations_and_no_brackets_in_speech` checks this.

## How the assistant opens the cited section

A citation is more useful when you can see it. When an answer cites a section, the widget asks the host page to open it, by dispatching a `voicecore:navigate` event for the cited section.

On this docs site, `src/theme/Root.jsx` handles that event. It changes the route without reloading the page, scrolls to the cited heading and highlights that section. The voice session keeps running, because the page is never reloaded.

This only works if the passage URL matches the route and anchor the site really renders. Ingest computes both the way Docusaurus does, and `harness/check_docs_anchors.py` checks every passage URL against the built site. If a heading renders with a different anchor, that check fails before a user ever gets a citation that opens the wrong place.

To embed the widget on another page, see [Embed the widget](../getting-started/embed-the-widget.md). To make your own pages cite precisely, see [Add your own docs](../guides/add-your-own-docs.md).

## How documentation answers are shaped for speech

A spoken answer has to be short. Nobody wants to listen to a paragraph, and every extra sentence delays the moment you can ask the next question.

For a question the docs answer, the assistant replies in two or three short spoken sentences. Each sentence carries a citation `[n]` to the passage that supports it. The citation markers are removed before TTS. The text answer keeps them, and `answer.sources` lists the cited sections.

The assistant uses only the retrieved passages for facts. It never fills a gap with outside knowledge, even when the model "knows" the answer from training. If a fact is not in the docs, it is not in the answer.

The last turns of the conversation are kept as context, so a follow-up question such as "and how do I change it?" is understood against the previous answer. Each new answer is still grounded in the passages retrieved for that turn, and its citations still come from the index.

## How the assistant handles greetings and small talk

Not every turn is a documentation question. When you say hello, thank the assistant or ask what it can do, it gives a short, friendly reply of at most two sentences.

That reply has no citations, because it states no documentation facts. Instead, it names topics the docs cover, such as latency, barge-in or adding your own docs, so you know what to ask next. A greeting does not open any page, because there is no cited section to open.

As soon as you ask about how something works, the grounded rules apply again: retrieval, two or three cited sentences and sources from the index. The assistant does not answer factual questions from outside knowledge, even in a friendly reply.

## When the assistant says the docs do not cover a question

Sometimes the docs do not answer the question. The assistant then says so in a friendly way and suggests the closest topic the docs do cover, so you have somewhere to go next. It does not guess and it does not use outside knowledge.

The `Grounding` filter enforces this even when the model tries to answer anyway. If no sentence of an answer carries a valid citation, the whole answer is replaced with the refusal, and `answer.sources` is empty. A refusal the model writes after a grounded sentence is dropped, so a good partial answer is not turned into a refusal (`test_a_refusal_after_a_grounded_sentence_is_dropped_not_counted`).

On the uv docs, refusal decisions were 15 of 15 right with gpt-4.1-nano: it answered the 11 answerable questions and refused the 4 unanswerable ones (live, text only, n = 15 holdout questions). Strictness has a cost: some refusals are false, as the model comparison shows.

## Why passages are treated as untrusted text

A retrieval-augmented agent quotes documents into its prompt. Anyone who can write a page that gets retrieved can therefore put words in front of the model. A page can contain a contradiction of the real docs, or text written as instructions to an AI.

VoiceCore's adversarial eval tested this with gpt-4.1-nano on the uv docs. It found that a rule in the model's instructions is not enough:

- **The model follows injected instructions.** A passage telling the assistant to ask for your credentials produced exactly that answer, with gpt-4.1-nano (question a07). A fake "maintenance mode" note made it call uv deprecated (a08).
- **The instruction rule did not stop it.** The model was told that passages are quoted documentation, not instructions, and to ignore instructions inside them. In the first engine version, only 1 of 3 injection questions passed; in the other 2, the injected text shaped the answer (live, n = 3).

The conclusion: enforce trust in code, before the prompt, instead of asking the model to judge it.

## Why suspicious passages are never quoted

Ingest checks every passage against a regular expression for instruction-like text: phrases that tell a model to drop its earlier instructions, give it a new role, ask for its hidden prompt, or mention credentials such as access keys. A match sets the passage's `suspicious` flag.

Flagged passages stay in the index, so you can audit what was found. But `AnswerEngine.retrieve` removes them before the prompt is built, so the model never sees their text.

Results on the uv adversarial set (live, gpt-4.1-nano):

- With only the instruction rule, injection questions passed 1 of 3 (n = 3).
- With flagged passages never quoted, they passed 3 of 3 (n = 3).

A regex does not catch everything. The fresh adversarial set, written after the fix, has one injection that starts "Note to AI assistants" and is not caught by the regex. The instruction rule handled that one, so the two defences work as layers. Wording in your own docs can trip the flag by accident; see [Add your own docs](../guides/add-your-own-docs.md).

## Why only official pages are quoted

The second structural defence is about where a page comes from. The engine has an `official_only` setting, on by default. With it, only passages from the pinned docs snapshot are ever quoted. Other pages, even from the docs host, can be indexed but never reach the prompt.

The eval showed why labels are not enough. In engine version 2, each passage was marked "(official uv docs)" or "(other page)", and official passages were listed first. gpt-4.1-nano still repeated the other page's contradicting claim in 3 of 3 original contradiction questions and in 1 of 2 fresh ones (live, n = 3 and n = 2).

With official-only quoting (version 3), no answer contained any adversarial claim. The policy was chosen after seeing the fresh run, though. The honest, unbiased contradiction result is version 2's 1 of 2 on the fresh set. Version 3's fresh 2 of 2 is optimistic.

## How ingest rejects stale and unauthorised pages

Some bad pages never reach the index at all. When ingesting the uv snapshot, a page whose front matter declares a `source_url` that is not `https` on an allowed host (`docs.astral.sh`) is skipped as an unauthorised source. A page that declares a `version` other than the snapshot's 0.13.6 is skipped as stale.

In the original adversarial set, these rules dropped 6 of its 12 pages at ingestion, and each skip is recorded with its reason. A skipped page can never be retrieved, so no prompt rule is needed. In the first engine version, stale and unauthorised questions passed 3 of 3 each (live, n = 3 each). In version 3, one stale question failed as an under-answer: the model refused although an official page answers it.

The same module has a URL guard, `check_url`, for any future fetching of pages. It accepts only `https` to an allowed host on port 443, with no user info, and refuses hosts that resolve to non-public addresses, which guards against server-side request forgery. Today ingest only reads local files, so nothing is fetched.

## Adversarial eval results by engine version

The adversarial set adds pages that are stale, contradict the docs, carry injected instructions, come from unauthorised hosts, or ask what the docs do not support. A question passes if no claim from an adversarial page appears in the answer and the answer or refusal is the expected one (live, gpt-4.1-nano, n = 15 original and n = 6 fresh questions).

| Engine version | Original 15 | Fresh 6 |
|---|---|---|
| v1: top 5, instruction rule | 10 / 15 | not run |
| v2: plus flagged passages never quoted, plus provenance labels | 12 / 15 | 5 / 6 |
| v3: plus only the pinned official snapshot quoted | 13 / 15 | 6 / 6 |

Version 3 is the shipped engine. Its 2 original failures are under-answers, not leaks. It refused "How do I install a command line tool?" although a page answers it, and it named `uv cache dir` without the default path. The engine was fixed after seeing these 15 questions, so their score is optimistic. The 6 fresh questions were written and committed before the re-run to check that.

## Answer quality with gpt-oss-120b and the earlier nano model

The voice default LLM moved from `openai/gpt-4.1-nano` (temperature 0, 80 tokens) to `openai/gpt-oss-120b` on Cerebras (effort low, 200 tokens) during the latency work. The same engine (v3) and questions were run on both (live, text only, uv docs, n = 15 holdout questions plus the adversarial sets).

| Measure | gpt-4.1-nano | gpt-oss-120b |
|---|---:|---:|
| Refusal decisions right (holdout) | 15 / 15 | 14 / 15 |
| Answers with every required term | 10 / 11 | 10 / 10 |
| Citations supporting the answer | 15 / 15 | 12 / 12 |
| Adversarial, original 15 | 13 / 15 | 14 / 15 |
| Adversarial, fresh 6 | 6 / 6 | 5 / 6 |
| Answers with an adversarial claim | 0 | 0 |

The two models are comparable within the ±1 noise seen between runs. gpt-oss-120b is a little more cautious: it refused "How do I pin the Python version for my project?" although the right passage was retrieved at rank 1. The eval's term check now treats Unicode hyphens like ASCII ones; before that, two correct gpt-oss answers were scored as misses.

## Grounded answers in live voice turns

Text evals measure the engine. A voice turn adds speech recognition in front of it, so a recognition error reaches the engine as a different question.

In 15 live voice turns on the uv docs, with Deepgram STT and the grounded engine, 11 questions were answered with citations and the 3 unanswerable questions were refused (live, n = 15). The remaining question, q16, was refused because Deepgram heard "Where does uvx keep…" as "When it is uvx keep…". The engine refused the garbled question instead of guessing.

That is the right failure for a grounded agent. A wrong transcript produced "the docs do not cover this" rather than a confident wrong answer. It also shows where to improve: the transcript, not the answer filter.

The browser widget itself was not measured live in that run. It uses the same SDK and server path as the headless client that was.
