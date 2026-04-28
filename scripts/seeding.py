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

    # ─── DB SERVICE ──────────────────────────────────────────────────────────
    "db-service": {
        "env": "production",
        "logs": [
            # 02:28 — baseline healthy
            f"2026-04-28 02:28:00.000 INFO  db-service [{REQ_ANALYTICS}] Analytics query started: SELECT * FROM events WHERE created_at > '2026-01-01' — estimated rows: 4200000",
            f"2026-04-28 02:28:01.200 INFO  db-service pool.monitor Connection pool status: active=12/50, idle=38, waiting=0",

            # 02:30 — degradation begins
            f"2026-04-28 02:30:00.441 WARN  db-service pool.monitor Connection pool status: active=31/50, idle=19, waiting=0 — sustained growth detected",
            f"2026-04-28 02:30:15.880 WARN  db-service [{REQ_ANALYTICS}] Slow query detected: running for 142s, acquired 18 connections — query: SELECT * FROM events WHERE created_at > '2026-01-01'",
            f"2026-04-28 02:30:45.003 WARN  db-service pool.monitor Connection pool status: active=43/50, idle=7, waiting=3 — WARNING: pool above 85% threshold",

            # 02:31 — approaching exhaustion
            f"2026-04-28 02:31:00.112 WARN  db-service pool.monitor Connection pool status: active=48/50, idle=2, waiting=8",
            f"2026-04-28 02:31:30.554 ERROR db-service pool.monitor Connection pool EXHAUSTED: active=50/50, idle=0, waiting=14 — new connections are being rejected",
            f"2026-04-28 02:31:31.001 ERROR db-service [{REQ_PAYMENT_1}] Connection acquisition timeout after 5000ms — pool exhausted, rejecting request from payment-service",
            f"2026-04-28 02:31:31.220 ERROR db-service [{REQ_USER_1}] Connection acquisition timeout after 5000ms — pool exhausted, rejecting request from user-service",

            # 02:32 — full exhaustion
            f"2026-04-28 02:32:00.000 ERROR db-service pool.monitor Connection pool CRITICAL: active=50/50, idle=0, waiting=22 — {REQ_ANALYTICS} holding 21 connections for 244s",
            f"2026-04-28 02:32:10.333 ERROR db-service [{REQ_PAYMENT_2}] Connection acquisition timeout after 5000ms — downstream services affected: auth-service, payment-service, user-service",

            # 02:35 — recovery
            f"2026-04-28 02:35:00.000 INFO  db-service dba.intervention Long-running query {REQ_ANALYTICS} terminated by DBA — held 21 connections for 427s, query killed",
            f"2026-04-28 02:35:00.441 INFO  db-service pool.monitor Connection pool recovering: active=29/50, idle=21, waiting=0 — freed 21 connections from killed query",
            f"2026-04-28 02:35:30.112 INFO  db-service pool.monitor Connection pool healthy: active=11/50, idle=39, waiting=0",
        ],
    },

    # ─── AUTH SERVICE ─────────────────────────────────────────────────────────
    "auth-service": {
        "env": "production",
        "logs": [
            # 02:29 — healthy
            f"2026-04-28 02:29:00.000 INFO  auth-service [{REQ_USER_1}] Token validation success: user=usr_8821 scope=read latency=3ms",
            f"2026-04-28 02:29:30.112 INFO  auth-service [{REQ_PAYMENT_1}] Token validation success: user=usr_4492 scope=write latency=4ms",

            # 02:31 — DB timeouts begin
            f"2026-04-28 02:31:31.550 ERROR auth-service [{REQ_PAYMENT_1}] Token validation failed: DB query timeout after 5000ms — unable to validate token for user=usr_4492 — db-service pool exhausted",
            f"2026-04-28 02:31:32.001 ERROR auth-service [{REQ_USER_1}] Token validation failed: DB query timeout after 5000ms — unable to validate token for user=usr_8821 — db-service pool exhausted",
            f"2026-04-28 02:31:45.220 WARN  auth-service circuit.breaker DB circuit breaker OPEN — 5 consecutive failures in 15s — all token validation will fail-fast for 60s",

            # 02:32 — full failure
            f"2026-04-28 02:32:00.000 ERROR auth-service [{REQ_PAYMENT_2}] Token validation REJECTED — circuit breaker OPEN — returning 503 to upstream",
            f"2026-04-28 02:32:01.112 ERROR auth-service [{REQ_USER_2}] Token validation REJECTED — circuit breaker OPEN — returning 503 to upstream",
            f"2026-04-28 02:33:00.000 ERROR auth-service health.check Health check FAILED — DB dependency unavailable — reporting unhealthy to load balancer",

            # 02:36 — recovery
            f"2026-04-28 02:36:00.333 INFO  auth-service circuit.breaker DB circuit breaker CLOSED — DB responding normally — latency=8ms",
            f"2026-04-28 02:36:01.000 INFO  auth-service [{REQ_USER_1}] Token validation success: user=usr_8821 scope=read latency=9ms — service restored",
            f"2026-04-28 02:36:01.550 INFO  auth-service health.check Health check PASSED — all dependencies healthy",
        ],
    },

    # ─── API GATEWAY ──────────────────────────────────────────────────────────
    "api-gateway": {
        "env": "production",
        "logs": [
            # 02:29 — healthy routing
            f"2026-04-28 02:29:00.100 INFO  api-gateway [{REQ_USER_1}] GET /api/v1/users/profile → auth-service 200 OK latency=5ms",
            f"2026-04-28 02:29:30.200 INFO  api-gateway [{REQ_PAYMENT_1}] POST /api/v1/payments → auth-service 200 OK latency=6ms",

            # 02:31 — upstream errors
            f"2026-04-28 02:31:32.100 ERROR api-gateway [{REQ_PAYMENT_1}] POST /api/v1/payments → auth-service 503 Service Unavailable latency=5012ms — upstream timeout",
            f"2026-04-28 02:31:32.900 ERROR api-gateway [{REQ_USER_1}] GET /api/v1/users/profile → auth-service 503 Service Unavailable latency=5011ms — upstream timeout",

            # 02:32 — circuit breaker on gateway side
            f"2026-04-28 02:32:05.000 WARN  api-gateway circuit.breaker auth-service circuit OPEN after 8 failures in 35s — fail-fast mode active for auth-required routes",
            f"2026-04-28 02:32:06.112 ERROR api-gateway [{REQ_PAYMENT_2}] POST /api/v1/payments → CIRCUIT OPEN — returning 503 to client without upstream call",
            f"2026-04-28 02:32:06.440 ERROR api-gateway [{REQ_USER_2}] GET /api/v1/users/profile → CIRCUIT OPEN — returning 503 to client without upstream call",

            # 02:33 — degraded mode
            f"2026-04-28 02:33:15.000 WARN  api-gateway degraded.mode All auth-required routes returning 503 — unauthenticated routes still serving — affected endpoints: /payments, /users, /orders",
            f"2026-04-28 02:34:30.000 ERROR api-gateway health.check Upstream dependency auth-service UNHEALTHY for 180s — SLO breach imminent",

            # 02:36 — recovery
            f"2026-04-28 02:36:30.220 INFO  api-gateway circuit.breaker auth-service circuit CLOSED — upstream healthy — resuming normal routing",
            f"2026-04-28 02:36:31.000 INFO  api-gateway [{REQ_PAYMENT_1}] POST /api/v1/payments → auth-service 200 OK latency=11ms — service restored",
        ],
    },

    # ─── PAYMENT SERVICE ──────────────────────────────────────────────────────
    "payment-service": {
        "env": "production",
        "logs": [
            # 02:29 — healthy
            f"2026-04-28 02:29:30.500 INFO  payment-service [{REQ_PAYMENT_1}] Payment initiated: user=usr_4492 amount=299.00 currency=INR — awaiting auth validation",
            f"2026-04-28 02:29:31.000 INFO  payment-service [{REQ_PAYMENT_1}] Auth validated OK — processing payment txn_id=txn_882211",

            # 02:31 — auth failures cascade
            f"2026-04-28 02:31:33.000 ERROR payment-service [{REQ_PAYMENT_1}] Auth validation failed for user=usr_4492 — auth-service returned 503 — transaction ABORTED txn_id=txn_882244",
            f"2026-04-28 02:31:34.112 ERROR payment-service [{REQ_PAYMENT_2}] Auth validation failed for user=usr_9921 — auth-service returned 503 — transaction ABORTED txn_id=txn_882245",
            f"2026-04-28 02:32:00.000 WARN  payment-service retry.policy Auth failures exceeding threshold — enabling payment hold mode — no new transactions will be initiated",

            # 02:33 — full hold
            f"2026-04-28 02:33:30.441 ERROR payment-service queue.monitor 47 transactions queued and blocked — auth dependency unavailable — oldest queued: 118s ago",
            f"2026-04-28 02:34:00.000 ERROR payment-service queue.monitor Transaction queue at capacity (50/50) — rejecting new payment requests with 503",

            # 02:37 — recovery
            f"2026-04-28 02:37:00.000 INFO  payment-service retry.policy Auth dependency restored — processing queued transactions — 47 transactions in queue",
            f"2026-04-28 02:37:01.220 INFO  payment-service [{REQ_PAYMENT_1}] Queued transaction processed: user=usr_4492 amount=299.00 txn_id=txn_882244 — SUCCESS",
        ],
    },

    # ─── USER SERVICE ─────────────────────────────────────────────────────────
    "user-service": {
        "env": "production",
        "logs": [
            # 02:29 — healthy
            f"2026-04-28 02:29:00.600 INFO  user-service [{REQ_USER_1}] Profile fetch: user=usr_8821 — auth OK — returned 200",
            f"2026-04-28 02:29:30.700 INFO  user-service [{REQ_USER_2}] Profile update: user=usr_3341 — auth OK — updated fields: [email, preferences]",

            # 02:31 — cascade hits
            f"2026-04-28 02:31:32.500 ERROR user-service [{REQ_USER_1}] Auth check failed for user=usr_8821 — auth-service 503 — aborting profile fetch",
            f"2026-04-28 02:31:33.001 ERROR user-service [{REQ_USER_2}] Auth check failed for user=usr_3341 — auth-service 503 — aborting profile update — data NOT written",
            f"2026-04-28 02:32:00.220 WARN  user-service cache.layer Serving stale cache for read-only profile requests — auth unavailable — cache TTL: 300s",

            # 02:33 — degraded reads from cache
            f"2026-04-28 02:33:00.000 WARN  user-service [{REQ_USER_1}] Serving STALE profile for user=usr_8821 from cache — age=240s — writes disabled",
            f"2026-04-28 02:34:00.000 WARN  user-service cache.layer Cache TTL expiring for 12 users — stale reads will fail after TTL — auth still unavailable",
            f"2026-04-28 02:34:01.330 ERROR user-service [{REQ_USER_2}] Cache expired for user=usr_3341 — auth still unavailable — returning 503",

            # 02:37 — recovery
            f"2026-04-28 02:37:00.500 INFO  user-service [{REQ_USER_1}] Auth restored — profile fetch live: user=usr_8821 — returned 200",
            f"2026-04-28 02:37:01.000 INFO  user-service cache.layer Auth dependency healthy — resuming live reads and writes — invalidating stale cache entries",
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


async def ingest_service(
    client: httpx.AsyncClient,
    service: str,
    config: dict,
) -> None:
    logs_text = "\n".join(config["logs"])
    payload = {
        "source_service": service,
        "source_env": config["env"],
        "logs": logs_text,
    }
    resp = await client.post(INGEST_URL, json=payload, timeout=60.0)
    resp.raise_for_status()
    data = resp.json()
    print(f"  ✓ {service:20s} → {data.get('chunks_ingested', '?')} chunks ingested")


async def main() -> None:
    print("=" * 60)
    print("INCIDENT SEEDING: DB pool exhaustion → cascading auth failure")
    print("=" * 60)
    print(f"\nIngesting {len(SERVICES)} services into {INGEST_URL}\n")

    async with httpx.AsyncClient() as client:
        for service, config in SERVICES.items():
            try:
                await ingest_service(client, service, config)
            except httpx.HTTPError as e:
                print(f"  ✗ {service:20s} → FAILED: {e}")

    print("\n" + "=" * 60)
    print(EXPECTED_INVESTIGATION)
    print("=" * 60)
    print("\nSuggested investigation queries:")
    print("  1. 'Why are payment-service and user-service failing since 02:31?'")
    print("  2. 'What caused the auth-service outage on April 28?'")
    print("  3. 'Correlate errors across services between 02:30 and 02:37'")
    print("  4. 'What was the root cause of the transaction failures?'")


if __name__ == "__main__":
    asyncio.run(main())