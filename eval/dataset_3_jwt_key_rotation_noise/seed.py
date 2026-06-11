"""
Seeds the JWT key rotation + heavy noise scenario.

Log timestamps are rewritten to the most recent past Monday at seed time so
"why are users getting 401 errors this morning" always resolves correctly
regardless of when the seed is run. The story template date (STORY_DATE) is
replaced with the computed anchor in every log line before ingestion.

Run:
    uv run python eval/dataset_3_jwt_key_rotation_noise/seed.py
"""
from __future__ import annotations
import asyncio
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from repi.core.container import get_container

LOGS_DIR = Path(__file__).parent / "logs"
STORY_DATE = "2026-05-04"  # original Monday in the story template

SERVICES = {
    "auth-svc.log":         "auth-svc",
    "verification-svc.log": "verification-svc",
    "api-gateway.log":      "api-gateway",
    "user-svc.log":         "user-svc",
    "cache-svc.log":        "cache-svc",
    "billing-svc.log":      "billing-svc",
}


def last_monday() -> date:
    today = datetime.now(timezone.utc).date()
    days_back = (today.weekday() - 0) % 7 or 7  # Monday=0; if today IS Monday, go back 7
    return today - timedelta(days=days_back)


async def main() -> None:
    anchor = last_monday()
    anchor_str = anchor.isoformat()
    print(f"Incident date: {anchor_str} (last Monday — story template: {STORY_DATE})")

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
            print(f"  {service:22s}  {count:4d} chunks  ({filename})")
            total += count

    print(f"\nSeeded {total} chunks across {len(SERVICES)} services into env=eval.")
    print(f"\nStarter query:")
    print('  POST /investigate {"query": "why are users getting 401 errors this morning"}')
    print(f"\nExpected timestamps in expected.json map to: {anchor_str}")


if __name__ == "__main__":
    asyncio.run(main())
