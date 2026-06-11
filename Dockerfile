# DevPath Navigator agent container.
# Python 3.12 base + uv for dep install. The agent trains Word2Vec at startup
# from BigQuery, so no model artifact needs to be baked in.

FROM python:3.12-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

# uv from the official distroless image
COPY --from=ghcr.io/astral-sh/uv:0.5.11 /uv /usr/local/bin/uv

# Run as a dedicated non-root user. Cloud Run's gVisor sandbox already
# limits blast radius, but dropping root inside the container is a cheap
# extra layer.
#
# Give appuser a real home directory: uv writes to ~/.cache/uv when it
# starts up, so `--no-create-home` causes the container to exit 2 with
# "Permission denied (os error 13)" on the very first `uv run`.
RUN useradd --uid 1000 --create-home --shell /usr/sbin/nologin appuser

WORKDIR /app

# Dependency layer (changes only when pyproject.toml / uv.lock change)
COPY --chown=appuser:appuser pyproject.toml uv.lock /app/
RUN uv sync --frozen --no-install-project --no-dev && chown -R appuser:appuser /app

# Source layer — agent/taxonomy.py loads data-gen/taxonomy.yaml at import time;
# the /eval-history endpoint imports eval.store.
COPY --chown=appuser:appuser data-gen/taxonomy.yaml /app/data-gen/taxonomy.yaml
COPY --chown=appuser:appuser embedding/              /app/embedding/
COPY --chown=appuser:appuser agent/                  /app/agent/
COPY --chown=appuser:appuser eval/                   /app/eval/

# Install the project itself (no-op here since we don't `import devpath_navigator`,
# but keeps the project metadata visible to uv if needed).
RUN uv sync --frozen --no-dev && chown -R appuser:appuser /app

USER appuser

ENV PORT=8080
EXPOSE 8080

# Cloud Run injects PORT — bind 0.0.0.0 and use $PORT.
# --loop uvloop and --http httptools are the uvicorn[standard] defaults; explicit for clarity.
CMD ["sh", "-c", "uv run --no-sync uvicorn agent.server:app --host 0.0.0.0 --port ${PORT} --loop uvloop --http httptools"]
