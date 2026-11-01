# One image, two processes (Step 09 Phase 11): the gateway (public :8080) and the orchestrator (:8765, private to
# the machine). Build context: the repository root (fly deploy . -c deploy/fly/fly.toml).
# The widget the gateway serves at /widget.js, built as in deploy/platform/gateway.Dockerfile.
FROM node:24-slim AS widget
RUN corepack enable
WORKDIR /src
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml tsconfig.base.json ./
COPY packages ./packages
COPY apps/demo ./apps/demo
RUN pnpm install --frozen-lockfile --filter "@voicecore/demo..."
RUN pnpm --filter @voicecore/demo build:widget

FROM golang:1.27 AS gateway
WORKDIR /src
COPY services/realtime-gateway/go.mod services/realtime-gateway/go.sum ./
RUN go mod download
COPY services/realtime-gateway/ ./
ARG VERSION=dev
RUN CGO_ENABLED=0 go build -trimpath -ldflags "-X main.version=${VERSION}" -o /gateway ./cmd/gateway

FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends tini && rm -rf /var/lib/apt/lists/*
COPY --from=ghcr.io/astral-sh/uv:0.12.21 /uv /uvx /bin/
WORKDIR /app
ENV UV_LINK_MODE=copy UV_COMPILE_BYTECODE=1 UV_NO_DEV=1
COPY pyproject.toml uv.lock .python-version ./
COPY services/agent-core ./services/agent-core
COPY services/console ./services/console
RUN uv sync --locked --no-dev --package voicecore  # the voice side only; the console member must exist for uv's lock
COPY apps/docs/docs ./apps/docs/docs
# Bake the embedding model and the docs vectors in, so a cold start (a stopped machine waking up) takes seconds.
RUN uv run python -c "from pathlib import Path; from voicecore.answer.ingest import docusaurus, ingest; from voicecore.answer.index import Index; Index(ingest(Path('apps/docs/docs'), site=docusaurus('http://localhost:3000/'))).dense('warm up', 1)"
COPY --from=gateway /gateway /usr/local/bin/gateway
COPY --from=widget /src/apps/demo/public/embed/voicecore.js /app/widget.js
COPY deploy/fly/entrypoint.sh /entrypoint.sh
ARG VERSION=dev
ENV VOICECORE_VERSION=$VERSION
RUN useradd --uid 10001 app && mkdir -p /data && chown app /data
# starts as root only to take ownership of Fly's root-owned volume; entrypoint.sh then drops to "app" (setpriv)
EXPOSE 8080
# plain tini, no -g: the script orders the shutdown itself (a group signal would stop both at once)
ENTRYPOINT ["/usr/bin/tini", "--", "/entrypoint.sh"]
