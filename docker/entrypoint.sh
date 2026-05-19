#!/bin/bash
# repi all-in-one entrypoint.
#
# Supervises uvicorn (FastAPI) and the Next.js standalone server in a single
# container. Either child exiting brings the container down so the orchestrator
# can restart cleanly — we don't try to keep one half up while the other is
# wedged.
set -euo pipefail

API_HOST="${REPI_API_HOST:-0.0.0.0}"
API_PORT="${REPI_API_PORT:-8000}"
WEB_HOST="${REPI_WEB_HOST:-0.0.0.0}"
WEB_PORT="${REPI_WEB_PORT:-3000}"

uvicorn repi.api:app --host "$API_HOST" --port "$API_PORT" &
API_PID=$!

(
    cd /app/web
    HOSTNAME="$WEB_HOST" PORT="$WEB_PORT" exec node server.js
) &
WEB_PID=$!

shutdown() {
    trap - INT TERM
    kill -TERM "$API_PID" "$WEB_PID" 2>/dev/null || true
    wait "$API_PID" "$WEB_PID" 2>/dev/null || true
    exit 0
}
trap shutdown INT TERM

# Block until either child exits, then take the rest of the container down.
wait -n "$API_PID" "$WEB_PID"
EXIT_CODE=$?
kill -TERM "$API_PID" "$WEB_PID" 2>/dev/null || true
wait "$API_PID" "$WEB_PID" 2>/dev/null || true
exit "$EXIT_CODE"
