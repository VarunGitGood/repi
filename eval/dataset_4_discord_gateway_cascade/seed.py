"""Seed dataset_4_discord_gateway_cascade.

Ingests 5 service logs from a Discord-style gateway cascade outage.
Root cause: Cassandra partition leader re-election in read-states-svc causes
a reconnect storm in gateway, which saturates message-svc's thread pool and
triggers 502s on cdn-edge. presence-svc is a red herring (elevated only due
to the reconnect flood, not a causal factor).
"""
from __future__ import annotations
import asyncio
from pathlib import Path
from repi.core.container import get_container
from repi.api.projects import resolve_project

LOGS_DIR = Path(__file__).parent / "logs"
PROJECT_NAME = "Demo"

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

        project = await resolve_project(session, PROJECT_NAME)
        ingestor = container.get_ingestor(session)
        for filename, service in SERVICES.items():
            path = LOGS_DIR / filename
            if not path.exists():
                print(f"  SKIP {service}: {path} not found")
                continue
            content = path.read_text()
            count = (await ingestor.ingest(
                content,
                source_service=service,
                source_env="eval",
                project_id=project.id,
            )).chunk_count
            print(f"  {service:20s}  {count:4d} chunks")
            total += count

    print(f"\nSeeded {total} chunks for dataset_4_discord_gateway_cascade (project={PROJECT_NAME})")
    return total


if __name__ == "__main__":
    asyncio.run(main())
