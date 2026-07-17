FROM python:3.13-slim-bookworm

# uv pinned by tag for reproducibility — the uv base image floats its uv version, so we don't use it
COPY --from=ghcr.io/astral-sh/uv:0.11.26 /uv /uvx /bin/

# UV_COMPILE_BYTECODE: generate .pyc at build time -> faster cold start
# UV_LINK_MODE=copy: avoid the hardlink-impossible warning between the cache mount and .venv
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

WORKDIR /srv
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen --no-dev --no-install-project
COPY app ./app
# One-off CLIs (command registration, install verification) — runnable via docker compose exec
COPY scripts ./scripts
# Avatar for channel webhooks the bot creates
COPY assets/png/avatar-brand-512.png ./assets/png/avatar-brand-512.png

# Exposed to the public internet, so don't run as root
# App files stay root-owned (read-only) to also block runtime tampering. Only the ledger is writable.
RUN useradd --create-home --shell /usr/sbin/nologin appuser \
    && mkdir -p /srv/data && chown appuser /srv/data
USER appuser

EXPOSE 8788
CMD [".venv/bin/uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8788"]
