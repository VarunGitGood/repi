"""
Seeds the insufficient-logging scenario.

Log timestamps are rewritten to the most recent past Thursday at seed time
so "why is the nightly report failing" / "last night" always resolves to
a recent date. The story template date (STORY_DATE) is replaced in every
log line before ingestion.

Run:
    poetry run python eval/dataset_2_insufficient_logging/seed.py
"""
from __future__ import annotations
import asyncio
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from repi.core.container import get_container

LOGS_DIR = Path(__file__).parent / "logs"
STORY_DATE = "2026-04-30"  # original Thursday in the story template

SERVICES = {
    "report-svc.log":        "report-svc",
    "cron-runner.log":       "cron-runner",
    "metrics-collector.log": "metrics-collector",
}


def last_thursday() -> date:
    today = datetime.now(timezone.utc).date()
    days_back = (today.weekday() - 3) % 7 or 7  # Thursday=3; if today IS Thursday, go back 7
    return today - timedelta(days=days_back)


async def main() -> None:
    anchor = last_thursday()
    anchor_str = anchor.isoformat()
    print(f"Incident date: {anchor_str} (last Thursday — story template: {STORY_DATE})")

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
            count = (await ingestor.ingest(content, source_service=service, source_env="eval")).chunk_count
            print(f"  {service:20s}  {count:4d} chunks  ({filename})")
            total += count

    print(f"\nSeeded {total} chunks across {len(SERVICES)} services into env=eval.")
    print(f"\nStarter query:")
    print('  POST /investigate {"query": "why is the nightly report failing"}')
    print(f"\nExpected timestamps in expected.json map to: {anchor_str}")


if __name__ == "__main__":
    asyncio.run(main())
