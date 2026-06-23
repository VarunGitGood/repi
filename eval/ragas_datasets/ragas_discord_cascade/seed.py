"""Seed the ragas_discord_cascade dataset.

Reuses log files from dataset_4_discord_gateway_cascade. Ingests all 5
services so the retrieval pipeline must surface read-states-svc evidence
even when the query only mentions gateway or disconnects.
"""
from __future__ import annotations
import asyncio
from pathlib import Path
from repi.core.container import get_container

LOGS_DIR = (
    Path(__file__).parent.parent.parent
    / "dataset_4_discord_gateway_cascade"
    / "logs"
)

SERVICES = {
    "read-states-svc.log": "read-states-svc",
    "gateway.log": "gateway",
    "message-svc.log": "message-svc",
    "presence-svc.log": "presence-svc",
    "cdn-edge.log": "cdn-edge",
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

    print(f"\nSeeded {total} chunks for ragas_discord_cascade")
    return total


if __name__ == "__main__":
    asyncio.run(main())
