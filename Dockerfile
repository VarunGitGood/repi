# syntax=docker/dockerfile:1.7

# ---- builder ----------------------------------------------------------------
FROM python:3.11-slim AS builder

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# Resolve and install runtime dependencies into /app/.venv (no project code yet,
# so this layer stays cached across source changes).
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project --no-dev

# Install the project itself.
COPY repi/ ./repi/
COPY README.md ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

# Trim caches & test/example dirs out of the venv before it travels to runtime.
RUN find /app/.venv -depth \
        \( -name '__pycache__' -o -name '*.pyc' -o -name '*.pyo' \) \
        -exec rm -rf {} + && \
    find /app/.venv -depth -type d \
        \( -name 'tests' -o -name 'test' -o -name 'examples' \) \
        -exec rm -rf {} + 2>/dev/null || true

# ---- runtime ----------------------------------------------------------------
FROM python:3.11-slim AS runtime

WORKDIR /app

# Bring across only the venv and the application package — no uv, no build
# caches, no source we don't need at runtime.
COPY --from=builder /app/.venv /app/.venv
COPY repi/ ./repi/

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

EXPOSE 8000
CMD ["uvicorn", "repi.api:app", "--host", "0.0.0.0", "--port", "8000"]
