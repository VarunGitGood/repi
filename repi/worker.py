import asyncio
import logging
import os
import signal
from datetime import datetime
from pathlib import Path
from typing import Dict, Set, Optional

from watchfiles import awatch, Change
from sqlmodel import select
from sqlalchemy.ext.asyncio import AsyncSession

from repi.core.container import get_container
from repi.models.schema import WatcherConfig, WatcherOffset
from repi.core.config import settings

logger = logging.getLogger("repi.worker")

class IngestionWorker:
    def __init__(self):
        self.container = get_container()
        self.watcher_configs: Dict[str, WatcherConfig] = {}
        self.offsets: Dict[str, int] = {}
        self.running = False
        self.refresh_interval = settings.WATCHER_CONFIG_REFRESH_SECS

    async def setup(self):
        await self.container.init_db()
        await self.refresh_configs()

    async def refresh_configs(self):
        """Poll DB for enabled watcher configs."""
        async with self.container.get_session() as session:
            statement = select(WatcherConfig).where(WatcherConfig.enabled == True)
            results = await session.exec(statement)
            configs = results.all()
            
            self.watcher_configs = {c.watch_path: c for c in configs}
            logger.info(f"Loaded {len(self.watcher_configs)} enabled watchers")

            statement_offsets = select(WatcherOffset)
            results_offsets = await session.exec(statement_offsets)
            offsets = results_offsets.all()
            self.offsets = {o.file_path: o.offset for o in offsets}

    async def get_or_create_offset(self, session: AsyncSession, watcher_config_id: str, file_path: str) -> int:
        statement = select(WatcherOffset).where(
            WatcherOffset.watcher_config_id == watcher_config_id,
            WatcherOffset.file_path == file_path
        )
        result = await session.exec(statement)
        db_offset = result.first()
        
        if db_offset:
            return db_offset.offset

        new_offset = WatcherOffset(
            watcher_config_id=watcher_config_id,
            file_path=file_path,
            offset=0
        )
        session.add(new_offset)
        await session.commit()
        return 0

    async def update_offset(self, session: AsyncSession, watcher_config_id: str, file_path: str, new_offset: int):
        statement = select(WatcherOffset).where(
            WatcherOffset.watcher_config_id == watcher_config_id,
            WatcherOffset.file_path == file_path
        )
        result = await session.exec(statement)
        db_offset = result.first()
        
        if not db_offset:
            db_offset = WatcherOffset(
                watcher_config_id=watcher_config_id,
                file_path=file_path,
                offset=new_offset
            )
        else:
            db_offset.offset = new_offset
            db_offset.updated_at = datetime.utcnow()
            db_offset.last_seen_at = datetime.utcnow()
        
        session.add(db_offset)
        await session.commit()
        self.offsets[file_path] = new_offset

    async def handle_file_change(self, file_path: str):
        config = None
        for path, c in self.watcher_configs.items():
            if file_path.startswith(path):
                config = c
                break
        
        if not config:
            return

        async with self.container.get_session() as session:
            current_offset = await self.get_or_create_offset(session, config.id, file_path)
            
            try:
                file_size = os.path.getsize(file_path)
                if file_size <= current_offset:
                    return

                with open(file_path, "r") as f:
                    f.seek(current_offset)
                    new_content = f.read()
                
                if not new_content.strip():
                    return

                ingestor = self.container.get_ingestor(session)
                stats = await ingestor.ingest(new_content, config.service_name)
                logger.info(f"Ingested {stats.chunk_count} chunks from {file_path}")

                await self.update_offset(session, config.id, file_path, file_size)
                
            except Exception as e:
                logger.error(f"Failed to ingest {file_path}: {e}")

    async def config_poll_loop(self):
        while self.running:
            await asyncio.sleep(self.refresh_interval)
            await self.refresh_configs()

    async def run(self):
        self.running = True
        await self.setup()

        asyncio.create_task(self.config_poll_loop())

        logger.info("Worker started, watching paths...")
        
        while self.running:
            paths = list(self.watcher_configs.keys())
            if not paths:
                await asyncio.sleep(5)
                continue

            async for changes in awatch(*paths):
                if not self.running:
                    break
                for change, path in changes:
                    if change in (Change.added, Change.modified):
                        await self.handle_file_change(path)

    def stop(self):
        self.running = False
        logger.info("Worker stopping...")

async def main():
    worker = IngestionWorker()
    
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, worker.stop)
    
    try:
        await worker.run()
    except asyncio.CancelledError:
        pass
    finally:
        logger.info("Worker exited")

if __name__ == "__main__":
    asyncio.run(main())
