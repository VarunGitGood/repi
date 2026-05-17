FROM python:3.11-slim

# Install uv (copy the static binary from the official image)
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# Install dependencies first for better layer caching
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project --no-dev

# Now copy the project and install it
COPY . .
RUN uv sync --frozen --no-dev

ENV PATH="/app/.venv/bin:$PATH"

CMD ["uvicorn", "repi.api:app", "--host", "0.0.0.0", "--port", "8000"]
