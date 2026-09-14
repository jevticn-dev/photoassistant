# Build context is the repository root — the same for all three images, so one
# .dockerignore governs what the daemon receives. See that file: without it the
# 50 GB dataset would be part of every build.

FROM python:3.14-slim AS runtime

# uv is copied from its own published image rather than installed with pip:
# a pinned binary, no build step, and no dependency of ours involved.
COPY --from=ghcr.io/astral-sh/uv:0.12.1 /uv /uvx /bin/

WORKDIR /app

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    PATH="/app/.venv/bin:$PATH" \
    # Where open_clip puts the weights it downloads on first use. They are data,
    # not code: 605 MB that would otherwise land in a container layer and be
    # fetched again by every new container. docker-compose.yml mounts a named
    # volume here, so the download happens once per machine.
    HF_HOME=/cache/huggingface

# Dependencies before source, so editing a module does not reinstall the world.
# --frozen installs exactly what uv.lock pins and fails if the lock file drifted
# from pyproject.toml; --no-dev leaves pytest and ruff out of the image.
#
# --extra embeddings is here because POST /recommend encodes the uploaded
# photograph at request time, so torch runs inside this container -- without it
# the image would start, pass its health check, and fail the first real request.
# It costs ~200 MB rather than the ~3 GB PyPI's build would, because
# pyproject.toml resolves torch from the CPU index on Linux (notes B83).
#
# README.md is here because pyproject.toml declares it as the package readme and
# hatchling refuses to build without it. It changes rarely, so it costs nothing
# on this layer.
COPY ml/pyproject.toml ml/uv.lock ml/README.md ./
# The cache mount keeps uv's downloaded wheels out of the layer. Without it this
# step weighed 2.52 GB against a 1.3 GB environment -- the difference was a copy
# of every wheel, baked in and never read again. UV_LINK_MODE=copy above is what
# makes a cache on another filesystem work.
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --extra service --extra embeddings --no-dev --no-install-project

COPY ml/photoassistant/ ./photoassistant/
COPY ml/service/ ./service/
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --extra service --extra embeddings --no-dev

EXPOSE 8000

# No curl in the image, and no reason to add one: Python can ask the question.
HEALTHCHECK --interval=10s --timeout=5s --retries=10 --start-period=10s \
    CMD python -c "import urllib.request, sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8000/health', timeout=3).status == 200 else 1)"

# --host 0.0.0.0 is required inside a container: the default 127.0.0.1 would
# refuse connections from the api container. This is safe only because the
# service publishes no port — see infra/docker-compose.yml.
CMD ["uvicorn", "service.main:app", "--host", "0.0.0.0", "--port", "8000"]
