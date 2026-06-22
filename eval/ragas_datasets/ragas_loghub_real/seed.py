"""Seed the ragas_loghub_real dataset.

Ingests real-world production logs from LogHub 2k (BGL supercomputer,
HDFS, Linux, Apache, OpenStack) as separate services. Tests retrieval
against genuine system failures — not synthetic scenarios.
"""
from __future__ import annotations
import asyncio
from pathlib import Path
from repi.core.container import get_container

LOGS_DIR = Path(__file__).parent.parent.parent / "loghub" / "raw"

SERVICES = {
    "BGL_2k.log": "bgl-supercomputer",
    "HDFS_2k.log": "hdfs-cluster",
    "Linux_2k.log": "linux-server",
    "Apache_2k.log": "apache-httpd",
    "OpenStack_2k.log": "openstack-nova",
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

    print(f"\nSeeded {total} chunks for ragas_loghub_real")
    return total


if __name__ == "__main__":
    asyncio.run(main())
