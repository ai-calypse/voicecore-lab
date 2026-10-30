#!/usr/bin/env bash
# Runs the orchestrator, then the gateway once the orchestrator is ready. On SIGTERM: the gateway first (its drain
# ends every session, up to 25 s), then the orchestrator (normally nothing left). If either process dies on its own,
# this exits non-zero, so Fly restarts the machine. Settings come from fly.toml [env] and fly secrets.
set -u
ENV_MODE=${VOICECORE_ENV:-prod}

/app/.venv/bin/python -m voicecore.server --host 127.0.0.1 --port 8765 --env "$ENV_MODE" --providers "${PROVIDERS:-live}" \
  --pool "${POOL:-public}" --metrics-port 9464 --docs-url "${DOCS_URL:-http://localhost:3000/}" &
orch=$!

for _ in $(seq 1 240); do # up to 2 minutes for the VAD model and the docs index
  /app/.venv/bin/python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8765/readyz', timeout=1)" 2>/dev/null && break
  kill -0 "$orch" 2>/dev/null || exit 1
  sleep 0.5
done

/usr/local/bin/gateway -addr 0.0.0.0:8080 -upstream ws://127.0.0.1:8765 -env "$ENV_MODE" -admin-addr 0.0.0.0:9091 \
  -origins "${ORIGINS:-localhost:*,127.0.0.1:*}" -hosts "${HOSTS:-localhost,127.0.0.1,::1}" \
  -trusted-proxies "${TRUSTED_PROXIES:-}" -sessions-per-ip-per-day "${SESSIONS_PER_IP_PER_DAY:-20}" &
gw=$!

stop() {
  kill -TERM "$gw" 2>/dev/null; wait "$gw"
  kill -TERM "$orch" 2>/dev/null; wait "$orch"
  exit 0
}
trap stop TERM INT

wait -n "$orch" "$gw" # returns when either exits on its own (a trapped SIGTERM runs stop instead)
code=$?
kill -TERM "$gw" "$orch" 2>/dev/null
exit $((code == 0 ? 1 : code))
