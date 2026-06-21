"""Seed the ragas_cross_service dataset.

Reuses log files from dataset_1_cascading_inventory_migration. Ingests all 5
services so the retrieval pipeline must surface inventory-svc evidence even
when the query only mentions checkout/cart.
"""
from __future__ import annotations
import asyncio
from pathlib import Path
from repi.core.container import get_container

LOGS_DIR = Path(__file__).parent.parent.parent / "dataset_1_cascading_inventory_migration" / "logs"

SERVICES = {
    "inventory-svc.log": "inventory-svc",
    "cart-svc.log": "cart-svc",
    "pricing-svc.log": "pricing-svc",
    "payment-svc.log": "payment-svc",
    "notification-svc.log": "notification-svc",
}


async def main() -> int:
    container = get_container()
    total = 0
    async with container.get_session() as session:
        from sqlalchemy import text
        await session.execute(text("TRUNCATE TABLE log_chunks RESTART IDENTITY CASCADE"))
        await session.commit()

        ingestor = container.get_ingestor(session)
        for filename, service in SERVICES.items():
            path = LOGS_DIR / filename
            if not path.exists():
                print(f"  SKIP {service}: {path} not found")
                continue
            content = path.read_text()
            count = (await ingestor.ingest(content, source_service=service, source_env="eval")).chunk_count
            print(f"  {service:20s}  {count:4d} chunks")
            total += count

    print(f"\nSeeded {total} chunks for ragas_cross_service")
    return total


if __name__ == "__main__":
    asyncio.run(main())
