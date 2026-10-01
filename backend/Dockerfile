# syntax=docker/dockerfile:1.7
# MFSG backend — FastAPI + geny-executor + Claude Code CLI.
# Node/Claude are built in a separate stage: no curl|bash repository bootstrap is
# executed in the runtime image.
FROM node:22-bookworm-slim AS claude
ARG CLAUDE_CODE_VERSION=2.1.236
RUN npm install -g @anthropic-ai/claude-code@${CLAUDE_CODE_VERSION} \
    && npm cache clean --force \
    && claude --version

FROM python:3.12-slim-bookworm AS runtime
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PIP_NO_CACHE_DIR=1 \
    OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 NUMEXPR_NUM_THREADS=1 \
    GENY_CLI_PREWARM=0 DISABLE_AUTOUPDATER=1 CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1 \
    UV_LINK_MODE=copy UV_COMPILE_BYTECODE=1 \
    HOME=/home/blackmoa \
    UV_CACHE_DIR=/root/.cache/uv
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates gosu libmagic1 tar tini \
       fonts-nanum \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 10001 blackmoa \
    && useradd --uid 10001 --gid 10001 --create-home --shell /bin/bash blackmoa
COPY --from=claude /usr/local/bin/node /usr/local/bin/node
COPY --from=claude /usr/local/bin/claude /usr/local/bin/claude
COPY --from=claude /usr/local/lib/node_modules /usr/local/lib/node_modules
COPY --from=ghcr.io/astral-sh/uv:0.12.10 /uv /uvx /bin/

WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen --no-dev --no-install-project
COPY alembic.ini ./
COPY alembic ./alembic
COPY src ./src
COPY entrypoint.sh ./entrypoint.sh
# HOME is the app user's, so uv used to cache into /home/blackmoa/.cache — 273MB and 9,319 files
# that the chown below then walked on every build (440s of a 583s deploy), and that shipped
# inside the image. UV_CACHE_DIR keeps it in a build cache mount instead.
RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen --no-dev \
    && chmod 0755 entrypoint.sh \
    && mkdir -p /data /home/blackmoa/.claude /home/blackmoa/.cache \
    && chown -R blackmoa:blackmoa /data /home/blackmoa \
    && /usr/local/bin/claude --version

ENV PATH="/app/.venv/bin:/usr/local/bin:${PATH}" \
    BLACKMOA_DATA_DIR=/data \
    BLACKMOA_CLAUDE_HOME=/home/blackmoa/.claude \
    BLACKMOA_CLAUDE_BINARY=/usr/local/bin/claude
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=5s --retries=3 --start-period=40s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3).read()" || exit 1
# entrypoint performs one-time root-owned volume repair, then execs
# `gosu blackmoa tini -- entrypoint.sh ...`, so runtime PID 1 is uid 10001.
ENTRYPOINT ["/app/entrypoint.sh"]
CMD ["api"]
