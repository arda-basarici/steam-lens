# The deploy unit: what CI tested is byte-for-byte what runs (DESIGN, "The box").
# Two stages so the shipped image carries the venv and the source, never uv or
# the build cache. The builder shares the runtime's base and copies in the uv
# that wrote uv.lock — a lockfile is only a reproducibility instrument when
# the resolver replaying it matches.
FROM python:3.13-slim-bookworm AS builder
COPY --from=ghcr.io/astral-sh/uv:0.11.26 /uv /usr/local/bin/uv

WORKDIR /app

# Bytecode compiled at build time (startup cost paid once, in CI), copy-mode
# links (the cache mount lives on another filesystem), no Python downloads
# (the base image's interpreter is the pinned one).
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=0

# Dependencies before source: the lockfile layer survives every code edit,
# so a rebuild after a src change replays this step from cache.
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project

COPY src ./src
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev


FROM python:3.13-slim-bookworm

# The image's code identity, baked at build time — no repo survives into a
# container, so `code_version()` reads this instead of asking git. An image
# that cannot state its provenance refuses to BUILD (fail at the cause, not
# at the first job): pass --build-arg CODE_VERSION=$(git rev-parse --short
# HEAD), +dirty when the tree has changes. CI supplies it in the ship step.
ARG CODE_VERSION
RUN test -n "$CODE_VERSION" || { echo "CODE_VERSION build arg required — an image without provenance refuses to build" >&2; exit 1; }
ENV STEAMLENS_CODE_VERSION=$CODE_VERSION

# Unprivileged uid 1000 — matches the default first user on the box, so the
# bind-mounted /data stays readable by host-side backups without chown games.
RUN groupadd --gid 1000 app && useradd --uid 1000 --gid app --no-create-home app

WORKDIR /app

# The venv's editable install points at /app/src; copying source to the same
# path keeps module-relative assets (templates, static, the ontology TOML)
# exactly where the dev layout has them.
COPY --from=builder /app/.venv ./.venv
COPY src ./src

# Container-shape defaults only — anything secret or host-specific (the API
# key, the mount location) comes from compose. 0.0.0.0 because 127.0.0.1 is
# unreachable from outside the container's namespace; /data is the bind-mount
# seam where SQLite outlives every rebuild.
ENV PATH="/app/.venv/bin:$PATH" \
    STEAMLENS_HOST=0.0.0.0 \
    STEAMLENS_PORT=8000 \
    STEAMLENS_DB_PATH=/data/serve.db \
    STEAMLENS_SERVE_LOG=/data/serve.log

EXPOSE 8000
USER app

CMD ["python", "-m", "steamlens.serve.main"]
