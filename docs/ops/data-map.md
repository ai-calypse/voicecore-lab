# Data map and threat model

**Status:** Step 09 slice 0.2, 2026-10-30.

**How this was produced:**

- **Sources.** Read-only code surveys, plus a `/cso` static run scoped to data flow (run `1793380417601-eb96d112614c8582`).
- **Result.** That run was offline, 10 minutes, completeness **partial**. It found no supported findings in the assessed scope. Nothing is hosted, so no deployed control was probed.
- **Threats listed here** are design risks with planned fixes. They are not reproduced vulnerabilities.

This page decides what logs may contain (Step 09 Phase 4) and what the privacy page promises (Phase 12).

## What each process handles

| Process | Stores (where, how long) | Logs (where) | Sends to |
|---|---|---|---|
| **Browser widget and SDK** | Nothing persistent. There is no `localStorage`, cookies or IndexedDB. The session token, session id and resume key live in memory only, and are gone when the tab closes. | Browser console (errors only) | Gateway: microphone PCM (16 kHz frames), typed questions, playout events. Pages: none. |
| **Go gateway** | In memory only: <ul><li>sessions, plus a 10 s resume window;</li><li>the token rate buckets per IP;</li><li>session counters.</li></ul>With `-trace FILE`, JSONL events (no text) go to that file, appended forever. **No rotation today.** | stderr, `slog` (JSON with `LOG_FORMAT=json`): start, stop, upstream dial failures, and `session started` / `session ended` with `session_id`, `reason` and `duration_ms` (P4). No IPs, tokens or resume keys. | Orchestrator: frames and events unchanged. Client: the agent's audio and events. |
| **Python orchestrator** | <ul><li>`benchmarks/spend_ledger.json`: amounts, labels with the session id, provider request ids. No text. Kept forever, since it is the money record.</li><li>`.cache/` holds embedding vectors and models.</li><li>With `--trace-dir`, a JSONL trace per session. Text fields are stripped unless `include_text`.</li></ul>**No retention job today.** | stdout, allow-list JSON formatter with `LOG_FORMAT=json` (P4): startup, session start, end and refusal, `provider error` with `provider` and `kind`. Key values and key-shaped strings are redacted; no transcripts. | Deepgram STT: microphone audio. OpenRouter (and Cerebras behind it): the question, the retrieved passages and the last turns. Deepgram TTS: the answer text. |
| **Docs site (nginx)** | Static files only | nginx access log in the container: client IP, path and user agent | — |
| **Providers** (outside this repo) | Under their own retention policies: Deepgram (audio and text), OpenRouter and its upstream (prompts) | — | — |

**Personal data that passes through:**

| Data | Where it goes | Where it is not kept |
|---|---|---|
| The user's voice (audio) | Deepgram | not stored by VoiceCore |
| The user's questions as text | the LLM provider, and the widget's on-screen log | traces, unless `include_text` is on; logs |
| Client IP | gateway memory (rate limits), nginx access logs | — |

**Secrets** are the API keys in `.env` (mode 600, gitignored) and `GATEWAY_SECRET` in env. Keys are sent only in provider request headers and are never logged. A secret scan runs before every commit; gitleaks replaces it in Step 09 Phase 7.

## Ranked threats and the planned fixes

| # | Threat | Today | Impact if exploited | Planned fix (Step 09) |
|---|---|---|---|---|
| 1 | **Spend abuse:** anyone who can reach a public gateway mints tokens and runs paid sessions | Tokens are free to mint (10 per minute per IP, 4 sessions per IP); there are per-session caps and a $5 project cap | Money, up to the caps | Turnstile on new sessions (P7); a `public` sub-pool with a daily cap and a per-IP daily quota (P9); a fail-fast prod config (P7) |
| 2 | **Spend caps reset** on a fresh deploy or cold start | The ledger is a local file | The caps stop protecting money | A Fly volume, with prod refusing to start without it (P11); Redis with AOF, and refusing an unseeded store (P10) |
| 3 | **Session takeover by resume:** someone with a valid token and a victim's `session_id` within 10 s gets the victim's audio and answers | **Fixed in P3 (2026-10-30):** a resume needs the 64-hex `resume_key` sent only to the owner in `welcome`, compared in constant time and never logged | Privacy: one conversation | Done (P3), before any log contains session ids (P4) |
| 4 | **Token replay** from many IPs within 60 s | **Fixed in P3 (2026-10-30):** tokens are single-use (nonce) and bound to the client IP; `X-Forwarded-For` is believed only from `-trusted-proxies` | Bypasses per-IP limits | Done (P3). Used nonces are per process until Redis (P10) |
| 5 | **Cross-site token minting** | `Access-Control-Allow-Origin: *` on `POST /v1/session` | Any site can embed the paid demo | CORS echoes only the allowed origins (P7) |
| 6 | **Operational data exposure:** `/debug/counters` and `/metrics` are public | Counters are public, though they hold no secrets | Information about load and drops | An admin listener that is not published (P5, P7) |
| 7 | **Secrets in logs or commits** | No key is logged today; there is a manual grep scan | Key theft, then spend | An allow-list log formatter with key redaction (P4); gitleaks in CI, scanning `benchmarks/raw` too (P7) |
| 8 | **Prompt injection through docs** | First-party docs only; injection-shaped passages are flagged and never quoted; citations are validated | Wrong or unsafe answers | Unchanged (Step 04); adversarial eval |
| 9 | **Unbounded retention** of trace and log files | No rotation or pruning | Privacy, disk | Traces off in prod; Loki compactor retention of 7 days (P5); the privacy page states retention per deployment (P12) |
| 10 | **Provider outage cascades** (not security, but availability) | No breakers; STT never reconnects | Sessions hang, or retries pile up | Breakers, STT reconnect, a per-turn deadline (P6) |

## What logs may contain (rule for Phase 4)

**Allowed fields:**

- `ts`, `level`, `logger`, `msg`;
- `session_id`, which is safe only after `resume_key` exists (P3);
- `gen`, `kind`, `reason`, `provider`, `duration_ms`.

**Never logged:**

- transcript or answer text;
- audio;
- API keys, `GATEWAY_SECRET`, `resume_key` or tokens;
- full IP addresses outside the gateway's rate-limit code.
