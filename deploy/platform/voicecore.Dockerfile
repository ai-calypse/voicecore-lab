# The voicecore image (Step 10, ADR 0005): the orchestrator or the console, chosen by the command in
# create-voicecore's compose.yml. Published as ghcr.io/ai-calypse/voicecore. Build context: the repository root.
FROM node:24-slim AS ui
RUN corepack enable
WORKDIR /src
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml tsconfig.base.json ./
COPY packages ./packages
COPY apps/console ./apps/console
RUN pnpm install --frozen-lockfile --filter "@voicecore/console..."
RUN pnpm --filter @voicecore/console exec vite build

FROM python:3.12-slim
# git: the console's Git sources (a hardened shallow clone, voicecore_console/sources.py)
RUN apt-get update && apt-get install -y --no-install-recommends git && rm -rf /var/lib/apt/lists/*
COPY --from=ghcr.io/astral-sh/uv:0.12.21 /uv /uvx /bin/
WORKDIR /app
ENV UV_LINK_MODE=copy UV_COMPILE_BYTECODE=1 UV_NO_DEV=1 PATH=/app/.venv/bin:$PATH
COPY pyproject.toml uv.lock .python-version ./
COPY services/agent-core ./services/agent-core
COPY services/console ./services/console
RUN uv sync --locked --no-dev --no-cache
# the shared embedding model, baked in: the first Publish and the first session need no download
RUN python -c "from voicecore.answer.index import embedder; list(embedder().query_embed('warm up'))"
COPY --from=ui /src/apps/console/dist /app/console-ui
ARG VERSION=dev
ENV VOICECORE_VERSION=$VERSION
# the named volumes start with the image's ownership, so both services can write theirs
RUN useradd --uid 10001 app && mkdir -p /data/agents /data/console /data/ledger /data/providers && chown -R app /data
USER app
EXPOSE 8765 8000
CMD ["python", "-m", "voicecore.server", "--host", "0.0.0.0"]
