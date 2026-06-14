import logging
from typing import List
from uuid import UUID, uuid4
from datetime import datetime
from fastapi import APIRouter, HTTPException, Depends
from sqlmodel import select

from repi.core.container import get_container
from repi.models.schema import WatcherConfig, WatcherOffset
from repi.api.schemas import (
    WatcherConfigCreate,
    WatcherConfigRead,
    WatcherConfigUpdate,
    WatcherStatus,
)

logger = logging.getLogger("repi.api.watchers")

router = APIRouter()

@router.post("/watchers", response_model=WatcherConfigRead)
async def create_watcher(config: WatcherConfigCreate):
    container = get_container()
    async with container.get_session() as session:
        # No project given → Default, so every watcher (and the chunks its
        # worker ingests) always lands in a project.
        project_id = config.project_id
        if project_id is None:
            from repi.api.projects import resolve_project
            project_id = (await resolve_project(session, None)).id
        db_config = WatcherConfig(
            service_name=config.service_name,
            watch_path=config.watch_path,
            env=config.env,
            enabled=config.enabled,
            project_id=project_id,
        )
        session.add(db_config)
        await session.commit()
        await session.refresh(db_config)
        return db_config

@router.get("/watchers", response_model=List[WatcherConfigRead])
async def list_watchers():
    container = get_container()
    async with container.get_session() as session:
        statement = select(WatcherConfig)
        results = await session.exec(statement)
        return results.all()

@router.patch("/watchers/{watcher_id}", response_model=WatcherConfigRead)
async def update_watcher(watcher_id: UUID, update: WatcherConfigUpdate):
    container = get_container()
    async with container.get_session() as session:
        db_config = await session.get(WatcherConfig, watcher_id)
        if not db_config:
            raise HTTPException(status_code=404, detail="Watcher not found")
        
        update_data = update.model_dump(exclude_unset=True)
        for key, value in update_data.items():
            setattr(db_config, key, value)
        
        db_config.updated_at = datetime.utcnow()
        session.add(db_config)
        await session.commit()
        await session.refresh(db_config)
        return db_config

@router.delete("/watchers/{watcher_id}")
async def delete_watcher(watcher_id: UUID):
    container = get_container()
    async with container.get_session() as session:
        db_config = await session.get(WatcherConfig, watcher_id)
        if not db_config:
            raise HTTPException(status_code=404, detail="Watcher not found")
        
        await session.delete(db_config)
        await session.commit()
        return {"ok": True}

@router.get("/watchers/{watcher_id}/status", response_model=List[WatcherStatus])
async def get_watcher_status(watcher_id: UUID):
    container = get_container()
    async with container.get_session() as session:
        statement = select(WatcherOffset).where(WatcherOffset.watcher_config_id == watcher_id)
        results = await session.exec(statement)
        return results.all()
