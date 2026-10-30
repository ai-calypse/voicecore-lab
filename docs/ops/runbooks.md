# Runbooks

**Status:** Step 09 Phase 5, 2026-10-30. One section per alert in `monitoring/prometheus/alerts.yml`; each alert's `runbook_url` points here. Grafana is http://127.0.0.1:3001 (dashboard "VoiceCore"), Prometheus http://127.0.0.1:9090, and the local pager is `docker compose logs -f alert-sink`. Targets: [slos.md](slos.md). Process: [incidents.md](incidents.md).

## Watchdog

**Meaning.** Always firing, by design. It proves Prometheus evaluates rules and Alertmanager delivers them.

**Check.** `docker compose logs alert-sink | grep Watchdog` shows a line at least every few minutes.

**Fix.** If it is missing, the alert pipeline is broken, and every other alert is silent too. Check `docker compose ps prometheus alertmanager alert-sink`, then Prometheus → Status → Rule health, then Alertmanager's log for webhook errors.

**Verify.** A new Watchdog line arrives in the sink.

## OrchestratorDown

**Meaning.** Prometheus could not scrape `agent-core:9464` for a minute. No new voice sessions can start. Severity critical; latency and error alerts are muted while it fires.

**Check.** `docker compose ps agent-core` (state, health, restarts), then `docker compose logs --tail 100 agent-core`. In Grafana, "Live sessions" falls to 0 and the logs panel shows the last lines before it stopped.

**Fix.**
- Crashed or killed: `docker compose up -d --wait agent-core`. If it crash-loops, read the traceback (`exc` in the JSON log line).
- Stuck loading (unhealthy, never ready): the VAD model or the docs index failed to load. Look for the error after "loading models".
- Out of memory: `docker stats`; the embedding model needs about 1 GB.

**Verify.** `curl -s 127.0.0.1:9464/metrics | head` answers, the alert resolves in the sink, and `uv run python harness/smoke.py` gets a cited answer.

## GatewayDown

**Meaning.** Prometheus could not scrape `gateway:9091` for a minute. Browsers cannot connect at all. Severity critical.

**Check.** `docker compose ps gateway`, `docker compose logs --tail 100 gateway`. A gateway waits for a healthy orchestrator, so check OrchestratorDown first.

**Fix.** `docker compose up -d --wait gateway`. A bind error ("address already in use") means another process holds :8080; see [troubleshooting](../../apps/docs/docs/guides/troubleshooting.md).

**Verify.** `curl -s 127.0.0.1:8080/readyz` returns `{"ready":true,...}`; the alert resolves.

## BudgetNearCap

**Meaning.** `voicecore_spend_usd{pool="usd"}` has been above $4.00 (80% of the $5.00 cap) for 5 minutes. At the cap, new live sessions are refused with reason `budget`.

**Check.** Grafana "Spend (USD) of the 5 USD cap". Then the ledger: `python -m voicecore.budget orphans` lists reservations that never settled, which count at their full amount.

**Fix.**
- Stop live spend first: restart with `PROVIDERS=mock`, or stop the orchestrator.
- If orphans explain the total, settle them by hand only after checking each one against the provider's own usage page.
- Never raise the cap without the owner's decision.

**Verify.** The gauge is below $4.00, or live providers are off.

## StageLatencyHigh

**Meaning.** Server-side endpoint to first audio p95 has been over 1,200 ms for 10 minutes (stage definition: `voicecore/stages.py`).

**Check.** Grafana "Stage p95 by stage" shows which stage grew:
- `stt_settle`: Deepgram STT finals are slow; check Deepgram's status page.
- `llm_first_token`: the model route changed or is overloaded. Look at the OpenRouter activity page for the provider actually used (`--llm-provider`, default Cerebras).
- `tts_first_audio`: Deepgram TTS is slow.
- every stage at once: the event loop is saturated; see EventLoopLagHigh.

**Fix.** Wait out a provider incident, or switch the route: `--llm-provider any` lets OpenRouter pick, and `--tts cartesia` only if credits allow. Shed load if the loop is the cause.

**Verify.** The p95 line drops under the threshold line in "Endpoint to first audio".

## ProviderErrorsHigh

**Meaning.** More than 2% of calls to one provider (`provider` label: `stt`, `llm` or `tts`) failed over 5 minutes.

**Check.** Grafana "Provider errors, by kind":
- `rate_limited`: 429s, too many sessions or a low key limit;
- `fatal`: a bad key, or a session cap reached (for TTS, the per-session character cap);
- `retryable`: network trouble or provider errors.

Logs: `{stack="voicecore", service="agent-core"} |= "provider error"` in Grafana's logs panel.

**Fix.**
- `fatal` from a key: the key was revoked or ran out; see [key rotation](key-rotation.md) (Step 09 Phase 7).
- `rate_limited`: lower concurrent sessions (`-max-sessions`), or raise the provider limit.
- `retryable`: check the provider's status page; the session already retries 429s and re-prompts on stalls.

**Verify.** The ratio falls under 2% on "Provider error ratio".

## EventLoopLagHigh

**Meaning.** The orchestrator's asyncio loop woke its 1 s timer more than 100 ms late (p95, 5 minutes). Voice activity detection runs on that loop, so every session's audio waits.

**Check.** Grafana "Event loop lag" against "Live sessions", and `docker stats agent-core` for CPU.

**Fix.** Too many sessions on one process: lower `-max-sessions` on the gateway, or add a copy (Step 09 Phase 10). The upgrade path is moving VAD to a thread pool (the `ponytail:` note in `server.py`).

**Verify.** p95 lag back under 100 ms.

## BreakerOpen

**Meaning.** A provider's circuit breaker has been open for a minute: after repeated failures, the orchestrator stopped calling it and fails fast (Step 09 Phase 6). Users hear "busy", or get text-only answers.

**Check.** Which provider: the `provider` label. Then that provider's errors, as in ProviderErrorsHigh.

**Fix.** Usually none: the breaker probes again after 30 s and closes on success. If the provider stays down, follow ProviderErrorsHigh.

**Verify.** The breaker state returns to closed (0) and the alert resolves.
