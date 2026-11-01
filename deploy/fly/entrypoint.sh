#!/usr/bin/env bash
# Runs the orchestrator, then the gateway once the orchestrator is ready. On SIGTERM: the gateway first (its drain
# ends every session, up to 25 s), then the orchestrator (normally nothing left). If either process dies on its own,
# or the orchestrator is not ready in 2 minutes, this exits non-zero, so Fly restarts the machine.
# With CONSOLE_ADMIN_PASSWORD (a fly secret) the console runs too, behind the gateway on the same host. Voice never
# depends on it: if it stops, only the dashboard is gone until the machine restarts.
# Settings come from fly.toml [env] and fly secrets.
set -u

if [ "$(id -u)" = 0 ]; then # Fly mounts its volume root-owned over /data: take it, then run as the app user
  chown app:app /data
  exec setpriv --reuid=app --regid=app --init-groups "$0" "$@"
fi

ENV_MODE=${VOICECORE_ENV:-prod}
orch="" gw="" con=""
stop() {
  [ -n "$gw" ] && { kill -TERM "$gw" 2>/dev/null; wait "$gw"; }
  [ -n "$orch" ] && { kill -TERM "$orch" 2>/dev/null; wait "$orch"; }
  [ -n "$con" ] && { kill -TERM "$con" 2>/dev/null; wait "$con"; }
  exit 0
}
trap stop TERM INT # before anything starts: a stop during the model load still drains

# AGENTS_DIR (on the volume): agents published there answer as data-agent="<id>", next to the default docs agent
[ -n "${AGENTS_DIR:-}" ] && mkdir -p "$AGENTS_DIR"

/app/.venv/bin/python -m voicecore.server --host 127.0.0.1 --port 8765 --env "$ENV_MODE" --providers "${PROVIDERS:-live}" \
  --pool "${POOL:-public}" --metrics-port 9464 --docs-url "${DOCS_URL:-http://localhost:3000/}" ${AGENTS_DIR:+--agents-dir "$AGENTS_DIR"} &
orch=$!

if [ -n "${CONSOLE_ADMIN_PASSWORD:-}" ]; then # niced: a Publish's embedding must not take the CPU a live call needs
  CONSOLE_DATA_DIR=/data/console VOICECORE_AGENTS_DIR="${AGENTS_DIR:-/data/agents}" VOICECORE_VECTORS_DIR=/data/console/vectors \
    CONSOLE_STATIC=/app/console-ui VOICECORE_PROVIDERS="${PROVIDERS:-live}" \
    nice -n 10 /app/.venv/bin/python -m voicecore_console serve --host 127.0.0.1 --port 8000 &
  con=$!
fi

ready=""
for _ in $(seq 1 240); do # up to 2 minutes for the VAD model and the docs index
  if /usr/local/bin/gateway -probe http://127.0.0.1:8765/readyz; then ready=1; break; fi
  kill -0 "$orch" 2>/dev/null || exit 1
  sleep 0.5 & wait $! # an interruptible sleep: the trap runs at once
done
[ -n "$ready" ] || { echo "orchestrator not ready after 2 minutes" >&2; kill -TERM "$orch"; wait "$orch"; exit 1; }

/usr/local/bin/gateway -addr 0.0.0.0:8080 -upstream ws://127.0.0.1:8765 -env "$ENV_MODE" -admin-addr 0.0.0.0:9091 \
  -origins "${ORIGINS:-localhost:*,127.0.0.1:*}" -hosts "${HOSTS:-localhost,127.0.0.1,::1}" \
  -trusted-proxies "${TRUSTED_PROXIES:-}" -sessions-per-ip-per-day "${SESSIONS_PER_IP_PER_DAY:-20}" \
  -widget /app/widget.js ${AGENTS_DIR:+-agents-dir "$AGENTS_DIR"} ${con:+-console http://127.0.0.1:8000} &
gw=$!

wait -n "$orch" "$gw" # returns when either exits on its own (a trapped SIGTERM runs stop instead)
code=$?
kill -TERM "$gw" "$orch" $con 2>/dev/null
exit $((code == 0 ? 1 : code))
