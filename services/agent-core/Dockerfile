# Build context: the repository root (the orchestrator answers from the docs site's Markdown in apps/docs/docs).
FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.12.21 /uv /uvx /bin/
WORKDIR /app
ENV UV_LINK_MODE=copy UV_COMPILE_BYTECODE=1 UV_NO_DEV=1
COPY pyproject.toml uv.lock .python-version ./
COPY services/agent-core ./services/agent-core
RUN uv sync --locked --no-dev
COPY apps/docs/docs ./apps/docs/docs
# Bake the embedding model and the docs vectors into the image, so the server starts in seconds.
RUN uv run python -c "from pathlib import Path; from voicecore.answer.ingest import docusaurus, ingest; from voicecore.answer.index import Index; Index(ingest(Path('apps/docs/docs'), site=docusaurus('http://localhost:3000/'))).dense('warm up', 1)"
RUN useradd --uid 10001 app && mkdir -p benchmarks /data && chown -R app /app/benchmarks /data  # /data: the prod ledger volume
USER app
EXPOSE 8765
ENTRYPOINT ["/app/.venv/bin/python", "-m", "voicecore.server", "--host", "0.0.0.0"]
CMD ["--providers", "mock"]
