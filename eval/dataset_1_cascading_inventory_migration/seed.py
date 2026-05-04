"""
Seeds the cascading-inventory-migration scenario.

Run:
    poetry run python eval/dataset_1_cascading_inventory_migration/seed.py
"""
from __future__ import annotations
import asyncio
from pathlib import Path

from repi.core.container import get_container

LOGS_DIR = Path(__file__).parent / "logs"

SERVICES = {
    "inventory-svc.log":    "inventory-svc",
    "cart-svc.log":         "cart-svc",
    "pricing-svc.log":      "pricing-svc",
    "payment-svc.log":      "payment-svc",
    "notification-svc.log": "notification-svc",
}


async def main() -> None:
    container = get_container()
    total = 0
    async with container.get_session() as session:
        ingestor = container.get_ingestor(session)
        for filename, service in SERVICES.items():
            path = LOGS_DIR / filename
            if not path.exists():
                print(f"  SKIP {service}: {path} not found")
                continue
            content = path.read_text()
            count = await ingestor.ingest(content, source_service=service, source_env="eval")
            print(f"  {service:20s}  {count:4d} chunks  ({path.name})")
            total += count

    print(f"\nSeeded {total} chunks across {len(SERVICES)} services into env=eval.")
    print("\nStarter query:")
    print('  POST /investigate {"query": "why did checkout break friday night"}')


if __name__ == "__main__":
    asyncio.run(main())
