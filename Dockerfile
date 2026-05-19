# syntax=docker/dockerfile:1.7

# ---- python builder ---------------------------------------------------------
FROM python:3.11-slim AS py-builder

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

# ---- web builder ------------------------------------------------------------
FROM node:20-bookworm-slim AS web-builder

WORKDIR /app/web

ENV NEXT_TELEMETRY_DISABLED=1

# Install full dep set (including devDependencies like tailwind/typescript that
# `next build` resolves at compile time). NODE_ENV is *not* set here — npm would
# otherwise skip devDependencies and the Turbopack build would fail.
COPY web/package.json web/package-lock.json ./
RUN --mount=type=cache,target=/root/.npm \
    npm ci --include=dev

COPY web/ ./

# Standalone build emits a self-contained node server + traced deps under
# .next/standalone — that is what we ship to the runtime image.
ENV NODE_ENV=production
RUN npm run build

# ---- runtime ----------------------------------------------------------------
FROM python:3.11-slim AS runtime

WORKDIR /app

# Pull just the `node` binary out of the official slim image. Both base images
# are debian-bookworm, so glibc is compatible. We do not need npm or globally
# installed modules at runtime — the Next.js standalone output is self-contained.
COPY --from=node:20-bookworm-slim /usr/local/bin/node /usr/local/bin/node

# Python venv + application package + DB schema (applied at startup by
# Container.init_db()).
COPY --from=py-builder /app/.venv /app/.venv
COPY repi/ ./repi/
COPY db/ ./db/

# Next.js standalone server + static assets. The standalone bundle includes a
# pruned node_modules and a top-level server.js entrypoint.
COPY --from=web-builder --chown=root:root /app/web/.next/standalone ./web/
COPY --from=web-builder --chown=root:root /app/web/.next/static ./web/.next/static
COPY --from=web-builder --chown=root:root /app/web/public ./web/public

COPY docker/entrypoint.sh /usr/local/bin/repi-entrypoint
RUN chmod +x /usr/local/bin/repi-entrypoint

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    NEXT_TELEMETRY_DISABLED=1 \
    NODE_ENV=production \
    REPI_API_HOST=0.0.0.0 \
    REPI_API_PORT=8000 \
    REPI_WEB_HOST=0.0.0.0 \
    REPI_WEB_PORT=3000 \
    REPI_API_INTERNAL_URL=http://127.0.0.1:8000

EXPOSE 3000 8000

CMD ["repi-entrypoint"]
