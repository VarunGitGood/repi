import logging
from typing import List
from uuid import UUID, uuid4
from datetime import datetime
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from sqlmodel import select

from repi.core.container import get_container
from repi.models.schema import WatcherConfig, WatcherOffset

logger = logging.getLogger("repi.api.watchers")

router = APIRouter()

class WatcherConfigCreate(BaseModel):
    service_name: str
    watch_path: str
    env: str = "production"
    enabled: bool = True

class WatcherConfigRead(BaseModel):
    id: UUID
    service_name: str
    watch_path: str
    env: str
    enabled: bool
    created_at: datetime
    updated_at: datetime

class WatcherConfigUpdate(BaseModel):
    service_name: str = None
    watch_path: str = None
    env: str = None
    enabled: bool = None

class WatcherStatus(BaseModel):
    file_path: str
    offset: int
    last_seen_at: datetime
    updated_at: datetime

@router.post("/watchers", response_model=WatcherConfigRead)
async def create_watcher(config: WatcherConfigCreate):
    container = get_container()
    async with container.get_session() as session:
        db_config = WatcherConfig(
            service_name=config.service_name,
            watch_path=config.watch_path,
            env=config.env,
            enabled=config.enabled
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
