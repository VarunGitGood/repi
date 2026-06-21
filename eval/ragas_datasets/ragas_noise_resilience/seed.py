"""Seed the ragas_noise_resilience dataset.

Generates ~200 INFO noise lines around 8 critical error lines across 2
services. Tests whether retrieval ranks the error signal above the noise.
"""
from __future__ import annotations
import asyncio
from repi.core.container import get_container


def _generate_noise_logs() -> tuple[str, str]:
    """Generate payment-gw and fraud-check-svc logs with high noise ratio."""
    payment_lines = []
    fraud_lines = []

    # fraud-check-svc: 100+ INFO lines then the batch overload
    for i in range(60):
        minute = 10 + (i * 1)
        if minute >= 60:
            break
        fraud_lines.append(
            f"2026-06-15T09:{minute:02d}:00Z [INFO] Fraud check completed for txn_fc{i:04d} in 48ms result=PASS"
        )

    for i in range(40):
        fraud_lines.append(
            f"2026-06-15T10:{i:02d}:00Z [INFO] Fraud check completed for txn_fc{1000+i:04d} in 52ms result=PASS"
        )

    # The batch job starts at 10:40
    fraud_lines.append("2026-06-15T10:40:00Z [INFO] Batch job started: retroactive fraud check for 10000 transactions from 2026-06-14")
    fraud_lines.append("2026-06-15T10:40:01Z [WARNING] Batch job submitted 10000 fraud checks to worker pool (capacity=50)")
    fraud_lines.append("2026-06-15T10:40:30Z [WARNING] Worker pool queue depth at 9800, all 50 workers busy")
    fraud_lines.append("2026-06-15T10:41:00Z [ERROR] Worker pool saturated: individual check latency spiked from 50ms to 8200ms")
    fraud_lines.append("2026-06-15T10:42:00Z [ERROR] Worker pool saturated: individual check latency at 12000ms, queue depth 9500")
    fraud_lines.append("2026-06-15T10:43:00Z [ERROR] Health check failed: /ready returned 503, latency 12400ms exceeds 5000ms threshold")

    # More noise after the errors
    for i in range(20):
        fraud_lines.append(
            f"2026-06-15T11:{i:02d}:00Z [INFO] Batch job progress: {500 + i * 500}/10000 checks completed"
        )
    fraud_lines.append("2026-06-15T11:30:00Z [INFO] Batch job completed, worker pool draining")
    fraud_lines.append("2026-06-15T11:35:00Z [INFO] Worker pool recovered, check latency back to 55ms")

    # payment-gw: 100+ INFO lines then the cascade
    for i in range(50):
        payment_lines.append(
            f"2026-06-15T09:{10 + i % 50:02d}:{i % 60:02d}Z [INFO] Payment authorized for order_{i:04d} amount=${ 20 + i * 3}.00 via stripe"
        )

    for i in range(50):
        payment_lines.append(
            f"2026-06-15T10:{i % 40:02d}:{i % 60:02d}Z [INFO] Payment authorized for order_{1000 + i:04d} amount=${50 + i * 2}.00 via stripe"
        )

    # Cascade from fraud-check-svc overload hits payment-gw at 10:42
    payment_lines.append("2026-06-15T10:42:00Z [WARNING] Fraud check for order_1055 timed out after 10000ms (threshold=5000ms)")
    payment_lines.append("2026-06-15T10:42:30Z [WARNING] Fraud check for order_1056 timed out after 10000ms")
    payment_lines.append("2026-06-15T10:43:00Z [ERROR] Payment authorization failed for order_1057: fraud check timeout, cannot proceed")
    payment_lines.append("2026-06-15T10:43:15Z [ERROR] Connection pool to fraud-check-svc exhausted (20/20 in use), queueing payments")
    payment_lines.append("2026-06-15T10:43:30Z [ERROR] Payment authorization failed for order_1058: gateway timeout waiting for fraud check slot")
    payment_lines.append("2026-06-15T10:44:00Z [ERROR] 5 payment authorizations failed in last 60s, fraud-check-svc unresponsive")
    payment_lines.append("2026-06-15T10:45:00Z [ERROR] Payment pipeline halted: fraud-check dependency unavailable")

    # More noise after
    for i in range(20):
        payment_lines.append(
            f"2026-06-15T11:{i + 35:02d}:00Z [INFO] Payment authorized for order_{2000 + i:04d} amount=${30 + i}.00 via stripe"
        )

    return "\n".join(fraud_lines), "\n".join(payment_lines)


async def main() -> int:
    container = get_container()
    fraud_logs, payment_logs = _generate_noise_logs()

    total = 0
    async with container.get_session() as session:
        from sqlalchemy import text
        await session.execute(text("TRUNCATE TABLE log_chunks RESTART IDENTITY CASCADE"))
        await session.commit()

        ingestor = container.get_ingestor(session)

        count = (await ingestor.ingest(fraud_logs, source_service="fraud-check-svc", source_env="eval")).chunk_count
        print(f"  fraud-check-svc  {count:4d} chunks")
        total += count

        count = (await ingestor.ingest(payment_logs, source_service="payment-gw", source_env="eval")).chunk_count
        print(f"  payment-gw       {count:4d} chunks")
        total += count

    print(f"\nSeeded {total} chunks for ragas_noise_resilience")
    return total


if __name__ == "__main__":
    asyncio.run(main())
