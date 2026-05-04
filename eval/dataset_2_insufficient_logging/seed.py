"""
Seeds the insufficient-logging scenario.

Run:
    poetry run python eval/dataset_2_insufficient_logging/seed.py
"""
from __future__ import annotations
import asyncio
from pathlib import Path

from repi.core.container import get_container

LOGS_DIR = Path(__file__).parent / "logs"

SERVICES = {
    "report-svc.log":        "report-svc",
    "cron-runner.log":       "cron-runner",
    "metrics-collector.log": "metrics-collector",
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
    print('  POST /investigate {"query": "why is the nightly report failing"}')


if __name__ == "__main__":
    asyncio.run(main())
