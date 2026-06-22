"""Seed the ragas_temporal_precision dataset.

Three distinct auth-svc failure episodes at different times of day, each with
a different root cause. Tests whether retrieval isolates the correct time
window's evidence.
"""
from __future__ import annotations
import asyncio
from repi.core.container import get_container

LOGS = """2026-06-10T13:30:00Z [INFO] auth-svc started, version 2.8.1
2026-06-10T13:30:00Z [INFO] Connected to Redis session store (pool=10)
2026-06-10T13:30:01Z [INFO] LDAP backend configured: ldap.internal:636
2026-06-10T13:45:00Z [INFO] Health check ok, 342 active sessions
2026-06-10T13:55:00Z [WARNING] Redis memory usage at 90% of maxmemory limit
2026-06-10T13:58:00Z [WARNING] Redis memory usage at 98% of maxmemory limit
2026-06-10T14:00:02Z [ERROR] Redis COMMAND rejected: OOM command not allowed when used memory > maxmemory
2026-06-10T14:00:02Z [ERROR] Session store write failed: cannot create new session for user_4421
2026-06-10T14:00:15Z [WARNING] Redis eviction policy triggered: evicting volatile-lru keys
2026-06-10T14:00:15Z [ERROR] Active session evicted for user_3812, next request will get 401
2026-06-10T14:00:30Z [ERROR] 401 Unauthorized for request_id=req_t001: session not found (evicted)
2026-06-10T14:00:45Z [ERROR] 401 Unauthorized for request_id=req_t002: session not found (evicted)
2026-06-10T14:01:00Z [ERROR] 401 Unauthorized for request_id=req_t003: session not found (evicted)
2026-06-10T14:01:15Z [ERROR] Session store write failed: cannot create new session for user_4488
2026-06-10T14:05:00Z [ERROR] 12 sessions evicted in last 5 minutes, 401 rate at 15%
2026-06-10T14:10:00Z [INFO] Ops increased Redis maxmemory from 256MB to 512MB
2026-06-10T14:10:30Z [INFO] Redis memory pressure relieved, writes resuming
2026-06-10T14:15:00Z [INFO] 401 rate back to baseline 0.1%
2026-06-10T15:00:00Z [INFO] Health check ok, 380 active sessions
2026-06-10T16:00:00Z [INFO] Health check ok, 401 active sessions
2026-06-10T17:00:00Z [INFO] Health check ok, 355 active sessions
2026-06-10T17:30:00Z [INFO] Health check ok, 362 active sessions
2026-06-10T17:55:00Z [WARNING] TLS certificate for ldap.internal expires in 5 minutes
2026-06-10T17:59:00Z [WARNING] TLS certificate for ldap.internal expires in 1 minute
2026-06-10T18:00:01Z [ERROR] LDAP bind failed: certificate has expired (ldap.internal:636)
2026-06-10T18:00:01Z [ERROR] TLS handshake error: X509_V_ERR_CERT_HAS_EXPIRED
2026-06-10T18:00:15Z [ERROR] Login failed for user_5001: LDAP backend unavailable (cert expired)
2026-06-10T18:00:30Z [ERROR] Login failed for user_5002: LDAP backend unavailable (cert expired)
2026-06-10T18:00:45Z [ERROR] Login failed for user_5003: LDAP backend unavailable (cert expired)
2026-06-10T18:01:00Z [ERROR] 500 Internal Server Error for request_id=req_t010: LDAP bind failed
2026-06-10T18:01:15Z [ERROR] 500 Internal Server Error for request_id=req_t011: LDAP bind failed
2026-06-10T18:05:00Z [ERROR] All login attempts failing, LDAP cert expired 5 minutes ago
2026-06-10T18:15:00Z [INFO] Ops renewed TLS certificate for ldap.internal
2026-06-10T18:15:30Z [INFO] LDAP bind successful after certificate renewal
2026-06-10T18:16:00Z [INFO] Login flow restored
2026-06-10T19:00:00Z [INFO] Health check ok, 310 active sessions
2026-06-10T20:00:00Z [INFO] Health check ok, 289 active sessions
2026-06-10T21:00:00Z [INFO] Health check ok, 245 active sessions
2026-06-10T21:30:00Z [INFO] Health check ok, 230 active sessions
2026-06-10T21:55:00Z [INFO] Config reload triggered by deploy pipeline
2026-06-10T21:55:01Z [INFO] Loading JWT signing key from vault
2026-06-10T21:55:01Z [WARNING] JWT signing key format changed: RSA-2048 -> unexpected format
2026-06-10T21:55:02Z [ERROR] JWT signing key validation failed: malformed PEM block
2026-06-10T22:00:01Z [ERROR] Token validation failed for request_id=req_t020: invalid signing key
2026-06-10T22:00:01Z [ERROR] 403 Forbidden: JWT signature verification failed
2026-06-10T22:00:15Z [ERROR] Token validation failed for request_id=req_t021: invalid signing key
2026-06-10T22:00:15Z [ERROR] 403 Forbidden: JWT signature verification failed
2026-06-10T22:00:30Z [ERROR] Token validation failed for request_id=req_t022: invalid signing key
2026-06-10T22:00:45Z [ERROR] Token validation failed for request_id=req_t023: invalid signing key
2026-06-10T22:01:00Z [ERROR] All authenticated requests returning 403, JWT key is corrupted
2026-06-10T22:05:00Z [ERROR] 403 rate at 100% for authenticated endpoints
2026-06-10T22:10:00Z [INFO] Ops rolled back JWT signing key to previous version
2026-06-10T22:10:30Z [INFO] Token validation restored
2026-06-10T22:15:00Z [INFO] 403 rate back to baseline
"""


async def main() -> int:
    container = get_container()
    total = 0
    async with container.get_session() as session:
        from sqlalchemy import text
        await session.execute(text("TRUNCATE TABLE log_chunks RESTART IDENTITY CASCADE"))
        await session.commit()

        ingestor = container.get_ingestor(session)
        count = (await ingestor.ingest(LOGS, source_service="auth-svc", source_env="eval")).chunk_count
        print(f"  auth-svc  {count:4d} chunks")
        total = count

    print(f"\nSeeded {total} chunks for ragas_temporal_precision")
    return total


if __name__ == "__main__":
    asyncio.run(main())
