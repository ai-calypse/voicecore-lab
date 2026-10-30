# Deploy guide

**Status:** Step 09 Phase 11, 2026-10-30. **Ready, not deployed.** Everything below is prepared and tested locally. Nothing has been deployed, and nothing should be until the owner decides to. A deploy costs money once the machine runs and providers are called.

## What gets deployed

One Fly app, `voicecore`, from [`deploy/fly/`](../../deploy/fly/): one machine (`shared-cpu-1x`, 1 GB, `iad`) running both processes from one image.

- **The gateway** listens on :8080, the only public port. Its admin listener is on :9091 (metrics, private).
- **The orchestrator** listens on :8765 on the machine itself; its metrics are on :9464 (private).
- **`entrypoint.sh`** runs both under `tini`. It starts as root only to take ownership of the volume (Fly mounts it root-owned), then runs everything as the `app` user. It starts the orchestrator first and the gateway once the orchestrator is ready. On Fly's SIGTERM it stops the gateway first (its drain ends every session, up to 25 s), then the orchestrator. If either process dies, or the orchestrator is not ready within 2 minutes, the script exits non-zero and Fly restarts the machine.
- **`fly.toml` settings:**
  - `kill_signal = "SIGTERM"` and `kill_timeout = 45` (Fly's defaults, SIGINT and 5 s, would cut the drain off);
  - a `/readyz` check;
  - two `[[metrics]]` entries;
  - the `voicecore_data` volume at `/data`, which holds the spend ledger.
- **Production checks.** In prod, both processes refuse to start with an unsafe setup:
  - the orchestrator refuses a ledger on the image's own filesystem, so a cold start could never reset the caps;
  - the gateway refuses a missing `GATEWAY_SECRET` or `TURNSTILE_SECRET`, local origins or hosts, broad origin patterns, or missing trusted proxies.
- **Public spend.** `POOL=public`: spend counts against the public sub-cap ($2.00 in total, $0.50 a day). Over it, visitors get text answers that point to the docs, with no paid call.

Tested locally by `harness/tests/test_fly_image.py` (`make fly-image-test`):
- the image boots and answers a smoke question;
- SIGTERM during a session ends it with `shutdown` and exits 0 within 45 s;
- a killed orchestrator makes the container exit non-zero;
- prod without its settings refuses to start.

## Before the first deploy

1. **Set provider spend limits outside VoiceCore.**
   - Give the OpenRouter key a credit limit.
   - Use a Deepgram project made for this deploy, with usage alerts.
   - The ledger caps are VoiceCore's own guard; these are the second line.
2. **Rotate the keys** that were used during development; see [key rotation](key-rotation.md).
3. **Look up Fly's proxy address range** and set it as `TRUSTED_PROXIES`. Until it is set, `-env prod` refuses to start. That is deliberate: without it every visitor would share the proxy's address for rate limits.
4. **Create a Turnstile widget** for the docs site's host and keep its sitekey and secret.
5. **Check current Fly pricing** for the machine and a 1 GB volume. Stopped machines cost nothing for CPU, but a volume is billed while it exists, a few cents a month.

## Commands

From the repository root:

```sh
fly apps create voicecore
fly volumes create voicecore_data --size 1 --region iad -a voicecore
fly secrets set -a voicecore \
  DEEPGRAM_API_KEY=... OPENROUTER_API_KEY=... \
  GATEWAY_SECRET="$(openssl rand -hex 32)" TURNSTILE_SECRET=... TRUSTED_PROXIES=...
fly deploy . -c deploy/fly/fly.toml
```

Or, once the `FLY_API_TOKEN` repository secret exists, run the `deploy` workflow by hand. It deploys and then runs a prod smoke check:
- `/readyz` returns 200;
- a token request without the human check gets 403;
- `/debug/counters` returns 404 on the public port.

**Check after deploy:**
- `fly logs -a voicecore` shows JSON lines with no `refusing to start`.
- `curl https://voicecore.fly.dev/readyz` answers `{"ready":true,...}`.
- One session through the docs site works, with the Turnstile sitekey set as `data-turnstile-sitekey` on the widget script.
- The ledger on the volume shows its reservation, settled at the session's end.

## Rollback

```sh
fly releases -a voicecore                 # find the last good release
fly deploy -a voicecore --image <image of that release>
```

The ledger is on the volume, so a rollback keeps the money record. To stop everything at once: `fly scale count 0 -a voicecore`. The volume, and its record, stay.

## The docs site

The docs site is static: `apps/docs` builds to plain files, served by its nginx image with the security headers. Deploy it as a second small Fly app or on any static host.
- Build it with `PUBLIC_GATEWAY=https://voicecore.fly.dev` (as `VOICECORE_GATEWAY` for the widget). That sets the widget's endpoint and the page's `connect-src`.
- Set `data-turnstile-sitekey` in `src/theme/Root.jsx` to the widget's sitekey.

## Scaling to two machines (documented, not deployed)

- **Shared state.** Add Redis (Upstash or a Fly app) and set `VOICECORE_LEDGER=redis://...` and the gateway's `-redis-url`.
- **Seeding.** Seed the Redis ledger once from the real file ledger on the volume (`python -m voicecore.budget migrate --from /data/spend_ledger.json --to redis://...`). From then on Redis is the money record for this deployment.
- **Resume routing.** Give each machine its Fly machine id as `-copy-id`. A resume that reaches the wrong machine must be answered with `fly-replay: instance=<owner>`. This is not built yet: one machine needs no routing.
- `fly scale count 2 -a voicecore`.

The scale profile (`docker compose --profile scale`) and [reports/load.md](../../reports/load.md) show the two-copy design working locally.
