# Key rotation

**Status:** Step 09 Phase 7, 2026-10-30. Rotate a key when it may have leaked (a log, a commit, a screenshot, a shared terminal), when someone with access leaves, and at least once before the repo goes public.

## Where the keys live

| Key | Used by | Local | Deployed (Step 09 Phase 11) |
|---|---|---|---|
| `DEEPGRAM_API_KEY` | orchestrator: speech-to-text and text-to-speech | `.env` (gitignored, mode 600) | `fly secrets set` |
| `OPENROUTER_API_KEY` | orchestrator: the answer model | `.env` | `fly secrets set` |
| `CARTESIA_API_KEY` | orchestrator, only with `--tts cartesia` | `.env` | not deployed |
| `GATEWAY_SECRET` | gateway: signs session tokens | env, optional locally | `fly secrets set` (required with `-env prod`) |
| `TURNSTILE_SECRET` | gateway: Cloudflare's human check | unset locally (no check) | `fly secrets set` (required with `-env prod`) |

Keys are read only on the server, never logged (the log formatter redacts loaded key values and key-shaped strings), and never sent to the browser.

## The order: new key first, old key last

1. **Make the new key** in the provider's console:
   - Deepgram: console.deepgram.com, the project's API keys. Use a project dedicated to VoiceCore with usage alerts on.
   - OpenRouter: openrouter.ai, Keys. Set a credit limit on the key itself.
   - Cartesia: the Cartesia console's API keys page.
   - `GATEWAY_SECRET`: `openssl rand -hex 32`. Rotating it invalidates every unused session token (60 s of them); open sessions keep working.
   - `TURNSTILE_SECRET`: Cloudflare dashboard, Turnstile, the widget's settings, rotate secret key.
2. **Put it where the service reads it.**
   - Local: edit `.env`, keep it mode 600 (`chmod 600 .env`), restart the stack.
   - Fly: `fly secrets set DEEPGRAM_API_KEY=... -a voicecore`. This restarts the machines, and they drain first.
   - Never paste a key into a command that is logged or shared, a commit, an issue, or a chat.
3. **Check that it works.**
   - Local: `uv run python harness/smoke.py` gets a cited answer in mock mode. For live keys, run one live session and check the ledger: `python -m voicecore.budget orphans` should list nothing new.
   - Deployed: `/readyz` 200, then one session through the site.
   - Logs: `docker compose logs agent-core | grep "provider error"` shows no `fatal` (a bad key is a fatal provider error).
4. **Revoke the old key** in the same console. Then check the provider's usage page for calls after the revocation: there should be none.
5. **Record it**: the date and which key, in `EXECUTION_STATUS.md` (never the key itself).

## Check that nothing leaked into git

Before any push, and always before making the repo public:

```sh
git grep --cached -nE 'sk-or-v1-|sk_car_|Token [0-9a-f]{32,}'   # tracked files
git log -p --all | grep -nE 'sk-or-v1-|sk_car_' | head             # history
```

The CI `secrets` job (gitleaks, Step 09 Phase 7) runs the same check on every push. If a key ever reaches a commit, rotate it first; removing it from history comes second, because anyone may have copied it already.
