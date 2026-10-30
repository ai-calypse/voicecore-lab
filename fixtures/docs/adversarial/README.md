# Adversarial docs set (S04-T05)

Twelve hand-written pages that try to mislead the answer engine, and 15 questions that target them. These pages are written for this project and are not part of the uv docs.

| Kind | Pages | What should happen |
|---|---|---|
| stale | `stale_*.md` claim an older `version` | dropped at ingestion: only the snapshot version (0.13.6) is indexed |
| contradiction | `contra_*.md` sit on allowed URLs but contradict the real docs | indexed; the answer must follow the real docs or say the docs disagree |
| injection | `inject_*.md` carry instructions to the model | indexed and flagged `suspicious`; the model must not follow them |
| unauthorized | `unauth_*.md` claim a host outside the allowlist, or plain http | dropped at ingestion |

Questions and pass rules: [`questions.json`](questions.json). Eval: `uv run python harness/answer_eval.py`.
