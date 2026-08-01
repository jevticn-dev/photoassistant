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
    PATH="/app/.venv/bin:$PATH"

# Dependencies before source, so editing a module does not reinstall the world.
# --frozen installs exactly what uv.lock pins and fails if the lock file drifted
# from pyproject.toml; --no-dev leaves pytest and ruff out of the image.
# README.md is here because pyproject.toml declares it as the package readme and
# hatchling refuses to build without it. It changes rarely, so it costs nothing
# on this layer.
COPY ml/pyproject.toml ml/uv.lock ml/README.md ./
RUN uv sync --frozen --extra service --no-dev --no-install-project

COPY ml/photoassistant/ ./photoassistant/
COPY ml/service/ ./service/
RUN uv sync --frozen --extra service --no-dev

EXPOSE 8000

# No curl in the image, and no reason to add one: Python can ask the question.
HEALTHCHECK --interval=10s --timeout=5s --retries=10 --start-period=10s \
    CMD python -c "import urllib.request, sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8000/health', timeout=3).status == 200 else 1)"

# --host 0.0.0.0 is required inside a container: the default 127.0.0.1 would
# refuse connections from the api container. This is safe only because the
# service publishes no port — see infra/docker-compose.yml.
CMD ["uvicorn", "service.main:app", "--host", "0.0.0.0", "--port", "8000"]
