"""
Seeds the cascading-inventory-migration scenario.

Log timestamps are rewritten to the most recent past Friday at seed time so
"why did checkout break friday night" always resolves correctly regardless
of when the seed is run. The story template date (STORY_DATE) is replaced
with the computed anchor in every log line before ingestion.

Run:
    poetry run python eval/dataset_1_cascading_inventory_migration/seed.py
"""
from __future__ import annotations
import asyncio
from datetime import date, timedelta
from pathlib import Path

from repi.core.container import get_container

LOGS_DIR = Path(__file__).parent / "logs"
STORY_DATE = "2026-05-01"  # original Friday in the story template

SERVICES = {
    "inventory-svc.log":    "inventory-svc",
    "cart-svc.log":         "cart-svc",
    "pricing-svc.log":      "pricing-svc",
    "payment-svc.log":      "payment-svc",
    "notification-svc.log": "notification-svc",
}


def last_friday() -> date:
    today = date.today()
    days_back = (today.weekday() - 4) % 7 or 7  # Friday=4; if today IS Friday, go back 7
    return today - timedelta(days=days_back)


async def main() -> None:
    anchor = last_friday()
    anchor_str = anchor.isoformat()
    print(f"Incident date: {anchor_str} (last Friday — story template: {STORY_DATE})")

    container = get_container()
    total = 0
    async with container.get_session() as session:
        from sqlalchemy import text
        print("Cleaning up existing chunks...")
        await session.execute(text("TRUNCATE TABLE log_chunks RESTART IDENTITY CASCADE"))
        await session.commit()

        ingestor = container.get_ingestor(session)
        for filename, service in SERVICES.items():
            path = LOGS_DIR / filename
            if not path.exists():
                print(f"  SKIP {service}: {path} not found")
                continue
            content = path.read_text().replace(STORY_DATE, anchor_str)
            count = await ingestor.ingest(content, source_service=service, source_env="eval")
            print(f"  {service:20s}  {count:4d} chunks  ({filename})")
            total += count

    print(f"\nSeeded {total} chunks across {len(SERVICES)} services into env=eval.")
    print(f"\nStarter query:")
    print('  POST /investigate {"query": "why did checkout break friday night"}')
    print(f"\nExpected timestamps in expected.json map to: {anchor_str}")


if __name__ == "__main__":
    asyncio.run(main())
