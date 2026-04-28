"""
Seeding script — Production incident simulation
================================================

INCIDENT: Database connection pool exhaustion → cascading auth failures

TIMELINE (all UTC, 2026-04-28 starting 02:30):
  02:30:00  db-service     Slow queries begin, pool at 60%
  02:31:00  db-service     Pool at 85%, warning threshold crossed
  02:32:00  auth-service   DB timeouts on token validation queries
  02:32:30  db-service     Pool exhausted (100%), new connections rejected
  02:33:00  auth-service   Token validation fails completely, returns 503
  02:33:15  api-gateway    Upstream auth-service returning 503, circuit opens
  02:33:30  payment-service Auth check fails, transactions blocked
  02:34:00  user-service   Profile fetch fails, auth dependency down
  02:34:30  api-gateway    Full degraded mode, all auth-required routes failing
  02:35:00  db-service     DBA kills long-running queries, pool begins recovering
  02:36:00  auth-service   DB connections restored, token validation resumes
  02:36:30  api-gateway    Circuit closes, upstream healthy
  02:37:00  payment-service Transactions resuming
  02:37:00  user-service   Recovery confirmed

EXPECTED INVESTIGATION PATH:
  1. get_service_summary across services → multiple services show ERRORs in same window
  2. search_logs auth-service → DB timeout errors on token validation
  3. search_logs db-service → connection pool exhaustion with timestamps
  4. find_co_occurring → db-service exhaustion and auth-service failures overlap
  5. get_timeline → causal chain: db slow → pool exhaust → auth fail → cascade
  6. LLM conclusion: root cause is db-service pool exhaustion, not auth-service failure

ROOT CAUSE: Long-running analytics query held DB connections, exhausting the pool.
IMPACT: All services requiring authentication were unavailable for ~4 minutes.
"""

from __future__ import annotations

import asyncio
import httpx
from datetime import datetime, timezone

INGEST_URL = "http://localhost:8000/api/v1/ingest"

# Shared request IDs — same req flows through multiple services
REQ_PAYMENT_1 = "req-a1b2c3d4-e5f6-7890-abcd-ef1234567890"
REQ_PAYMENT_2 = "req-b2c3d4e5-f6a7-8901-bcde-f12345678901"
REQ_USER_1    = "req-c3d4e5f6-a7b8-9012-cdef-123456789012"
REQ_USER_2    = "req-d4e5f6a7-b8c9-0123-defa-234567890123"
REQ_ANALYTICS = "req-e5f6a7b8-c9d0-1234-efab-345678901234"  # the villain


SERVICES: dict[str, dict] = {

    # ─── DB SERVICE (less obvious now) ───────────────────────────────────────
    "db-service": {
        "env": "production",
        "logs": [
            f"2026-04-28 02:28:00.000 INFO  db-service [{REQ_ANALYTICS}] Analytics query started: SELECT * FROM events WHERE created_at > '2026-01-01'",
            f"2026-04-28 02:30:00.441 WARN  db-service pool.monitor active=31/50 idle=19 waiting=0",
            f"2026-04-28 02:30:45.003 WARN  db-service pool.monitor active=43/50 idle=7 waiting=3",
            f"2026-04-28 02:31:00.112 WARN  db-service pool.monitor active=48/50 idle=2 waiting=8",
            
            # ❌ removed "EXHAUSTED"
            f"2026-04-28 02:31:30.554 ERROR db-service pool.monitor active=50/50 idle=0 waiting=14 — connection acquisition latency > 5s",
            
            # subtle clue instead of explicit
            f"2026-04-28 02:32:00.000 ERROR db-service pool.monitor active=50/50 idle=0 waiting=22 — long-running request {REQ_ANALYTICS} holding multiple connections",
            
            # out-of-order log
            f"2026-04-28 02:30:15.880 WARN  db-service [{REQ_ANALYTICS}] Slow query running >140s — scanning events table",
            
            # recovery
            f"2026-04-28 02:35:00.000 INFO  db-service dba.intervention Query {REQ_ANALYTICS} terminated",
            f"2026-04-28 02:35:30.112 INFO  db-service pool.monitor active=11/50 idle=39 waiting=0",
        ],
    },

    # ─── AUTH SERVICE (false lead injected) ──────────────────────────────────
    "auth-service": {
        "env": "production",
        "logs": [
            f"2026-04-28 02:29:00.000 INFO  auth-service [{REQ_USER_1}] Token validation success",

            # 🔥 FALSE LEAD: JWT issue
            f"2026-04-28 02:31:20.000 WARN  auth-service jwt Invalid signature detected for token kid=abc123",
            
            # real issue (but less obvious)
            f"2026-04-28 02:31:31.550 ERROR auth-service [{REQ_PAYMENT_1}] Token validation failed: upstream timeout after 5000ms",
            f"2026-04-28 02:31:32.001 ERROR auth-service [{REQ_USER_1}] Token validation failed: upstream timeout after 5000ms",

            f"2026-04-28 02:31:45.220 WARN  auth-service circuit.breaker OPEN after repeated failures",

            f"2026-04-28 02:32:00.000 ERROR auth-service [{REQ_PAYMENT_2}] Request rejected — circuit open",

            # recovery
            f"2026-04-28 02:36:00.333 INFO  auth-service circuit.breaker CLOSED",
        ],
    },

    # ─── API GATEWAY ─────────────────────────────────────────────────────────
    "api-gateway": {
        "env": "production",
        "logs": [
            f"2026-04-28 02:29:00.100 INFO  api-gateway [{REQ_USER_1}] GET /profile → 200",
            
            f"2026-04-28 02:31:32.100 ERROR api-gateway [{REQ_PAYMENT_1}] upstream timeout → auth-service",
            f"2026-04-28 02:32:05.000 WARN  api-gateway circuit OPEN auth-service",

            # noise-like wording
            f"2026-04-28 02:33:15.000 WARN  api-gateway degraded mode — some routes failing",
        ],
    },

    # ─── PAYMENT SERVICE ─────────────────────────────────────────────────────
    "payment-service": {
        "env": "production",
        "logs": [
            f"2026-04-28 02:29:30.500 INFO  payment-service [{REQ_PAYMENT_1}] Payment initiated",

            f"2026-04-28 02:31:33.000 ERROR payment-service [{REQ_PAYMENT_1}] Auth dependency failure",
            f"2026-04-28 02:32:00.000 WARN  payment-service retry threshold exceeded",

            f"2026-04-28 02:33:30.441 ERROR payment-service queue backlog growing",
        ],
    },

    # ─── USER SERVICE ────────────────────────────────────────────────────────
    "user-service": {
        "env": "production",
        "logs": [
            f"2026-04-28 02:29:00.600 INFO  user-service [{REQ_USER_1}] Profile fetch OK",

            f"2026-04-28 02:31:32.500 ERROR user-service [{REQ_USER_1}] Auth dependency failed",
            f"2026-04-28 02:32:00.220 WARN  user-service serving stale cache",

            f"2026-04-28 02:34:01.330 ERROR user-service cache expired — request failed",
        ],
    },

    # ─── NOISE: CACHE SERVICE ────────────────────────────────────────────────
    "cache-service": {
        "env": "production",
        "logs": [
            f"2026-04-28 02:31:10.000 WARN  cache-service Redis latency spike 120ms",
            f"2026-04-28 02:32:15.000 WARN  cache-service Evictions increasing",
        ],
    },

    # ─── NOISE: EMAIL SERVICE ────────────────────────────────────────────────
    "email-service": {
        "env": "production",
        "logs": [
            f"2026-04-28 02:31:40.000 ERROR email-service SMTP timeout to provider",
            f"2026-04-28 02:32:20.000 WARN  email-service retrying failed sends",
        ],
    },
}


EXPECTED_INVESTIGATION = """
EXPECTED INVESTIGATION OUTCOME
================================
Query: "Why are payment and user services failing since 02:31?"

Root cause: db-service connection pool exhausted due to long-running analytics
query (req-e5f6a7b8) holding 21 connections for 427 seconds.

Causal chain:
  1. Analytics query started at 02:28, accumulated 18 DB connections
  2. DB pool hit 85% at 02:30:45, then 100% at 02:31:30
  3. auth-service token validation queries timed out (requires DB lookup)
  4. auth-service circuit breaker opened at 02:31:45
  5. api-gateway detected upstream failures, opened its own circuit at 02:32:05
  6. payment-service blocked all new transactions at 02:32:00
  7. user-service fell back to stale cache reads, then failed when cache expired
  8. DBA killed analytics query at 02:35:00, freeing 21 connections
  9. Full recovery by 02:37:00

Impacted services: auth-service, api-gateway, payment-service, user-service
Not directly impacted: db-service itself (it was the origin, still serving other queries)
Confidence: high (request IDs correlate across services, timestamps align)
"""


import asyncio
from datetime import datetime, timezone
from src.app.core.container import Container

# Shared request IDs — same req flows through multiple services
REQ_PAYMENT_1 = "req-a1b2c3d4-e5f6-7890-abcd-ef1234567890"
REQ_PAYMENT_2 = "req-b2c3d4e5-f6a7-8901-bcde-f12345678901"
REQ_USER_1    = "req-c3d4e5f6-a7b8-9012-cdef-123456789012"
REQ_USER_2    = "req-d4e5f6a7-b8c9-0123-defa-234567890123"
REQ_ANALYTICS = "req-e5f6a7b8-c9d0-1234-efab-345678901234"  # the villain

SERVICES: dict[str, dict] = {
    # ─── DB SERVICE (less obvious now) ───────────────────────────────────────
    "db-service": {
        "env": "production",
        "logs": [
            f"2026-04-28 02:28:00.000 INFO  db-service [{REQ_ANALYTICS}] Analytics query started: SELECT * FROM events WHERE created_at > '2026-01-01'",
            f"2026-04-28 02:30:00.441 WARN  db-service pool.monitor active=31/50 idle=19 waiting=0",
            f"2026-04-28 02:30:45.003 WARN  db-service pool.monitor active=43/50 idle=7 waiting=3",
            f"2026-04-28 02:31:00.112 WARN  db-service pool.monitor active=48/50 idle=2 waiting=8",
            f"2026-04-28 02:31:30.554 ERROR db-service pool.monitor active=50/50 idle=0 waiting=14 — connection acquisition latency > 5s",
            f"2026-04-28 02:32:00.000 ERROR db-service pool.monitor active=50/50 idle=0 waiting=22 — long-running request {REQ_ANALYTICS} holding multiple connections",
            f"2026-04-28 02:30:15.880 WARN  db-service [{REQ_ANALYTICS}] Slow query running >140s — scanning events table",
            f"2026-04-28 02:35:00.000 INFO  db-service dba.intervention Query {REQ_ANALYTICS} terminated",
            f"2026-04-28 02:35:30.112 INFO  db-service pool.monitor active=11/50 idle=39 waiting=0",
        ],
    },
    # ... (other services remain same)
    "auth-service": {
        "env": "production",
        "logs": [
            f"2026-04-28 02:29:00.000 INFO  auth-service [{REQ_USER_1}] Token validation success",
            f"2026-04-28 02:31:20.000 WARN  auth-service jwt Invalid signature detected for token kid=abc123",
            f"2026-04-28 02:31:31.550 ERROR auth-service [{REQ_PAYMENT_1}] Token validation failed: upstream timeout after 5000ms",
            f"2026-04-28 02:31:32.001 ERROR auth-service [{REQ_USER_1}] Token validation failed: upstream timeout after 5000ms",
            f"2026-04-28 02:31:45.220 WARN  auth-service circuit.breaker OPEN after repeated failures",
            f"2026-04-28 02:32:00.000 ERROR auth-service [{REQ_PAYMENT_2}] Request rejected — circuit open",
            f"2026-04-28 02:36:00.333 INFO  auth-service circuit.breaker CLOSED",
        ],
    },
    "api-gateway": {
        "env": "production",
        "logs": [
            f"2026-04-28 02:29:00.100 INFO  api-gateway [{REQ_USER_1}] GET /profile → 200",
            f"2026-04-28 02:31:32.100 ERROR api-gateway [{REQ_PAYMENT_1}] upstream timeout → auth-service",
            f"2026-04-28 02:32:05.000 WARN  api-gateway circuit OPEN auth-service",
            f"2026-04-28 02:33:15.000 WARN  api-gateway degraded mode — some routes failing",
        ],
    },
    "payment-service": {
        "env": "production",
        "logs": [
            f"2026-04-28 02:29:30.500 INFO  payment-service [{REQ_PAYMENT_1}] Payment initiated",
            f"2026-04-28 02:31:33.000 ERROR payment-service [{REQ_PAYMENT_1}] Auth dependency failure",
            f"2026-04-28 02:32:00.000 WARN  payment-service retry threshold exceeded",
            f"2026-04-28 02:33:30.441 ERROR payment-service queue backlog growing",
        ],
    },
    "user-service": {
        "env": "production",
        "logs": [
            f"2026-04-28 02:29:00.600 INFO  user-service [{REQ_USER_1}] Profile fetch OK",
            f"2026-04-28 02:31:32.500 ERROR user-service [{REQ_USER_1}] Auth dependency failed",
            f"2026-04-28 02:32:00.220 WARN  user-service serving stale cache",
            f"2026-04-28 02:34:01.330 ERROR user-service cache expired — request failed",
        ],
    },
    "cache-service": {
        "env": "production",
        "logs": [
            f"2026-04-28 02:31:10.000 WARN  cache-service Redis latency spike 120ms",
            f"2026-04-28 02:32:15.000 WARN  cache-service Evictions increasing",
        ],
    },
    "email-service": {
        "env": "production",
        "logs": [
            f"2026-04-28 02:31:40.000 ERROR email-service SMTP timeout to provider",
            f"2026-04-28 02:32:20.000 WARN  email-service retrying failed sends",
        ],
    },
}

async def main() -> None:
    print("=" * 60)
    print("INCIDENT SEEDING: DB pool exhaustion → cascading auth failure")
    print("=" * 60)

    container = Container()
    await container.init_db()
    
    async with container.async_session_maker() as session:
        ingestor = container.get_ingestor(session)
        for service, config in SERVICES.items():
            print(f"Ingesting {service}...")
            logs_text = "\n".join(config["logs"])
            chunks_ingested = await ingestor.ingest(
                logs=logs_text,
                source_service=service,
                source_env=config["env"]
            )
            print(f"  ✓ {service:20s} → {chunks_ingested} chunks ingested")

    print("\nSeeding complete.")

if __name__ == "__main__":
    asyncio.run(main())