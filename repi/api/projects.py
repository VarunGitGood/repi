"""Projects API (UX redesign P1).

A project is a logical system/application — workers, services, conversations
and investigations are scoped to one. `resolve_project` is the shared
name-or-id resolver used by /ingest (and the worker indirectly via
watcher_configs.project_id).
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, List, Optional
from uuid import UUID

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import text as sa_text
from sqlmodel import select

from repi.core.container import get_container
from repi.models.schema import Project

logger = logging.getLogger("repi.api.projects")

router = APIRouter()

DEFAULT_PROJECT_NAME = "Default"

# Defaults merged under explicit per-project settings when read.
DEFAULT_SETTINGS: dict[str, Any] = {
    "default_timeline_window": "5h",
    "auto_load_timeline": True,
    "max_events": 25,
}


def effective_settings(project: Project) -> dict[str, Any]:
    return {**DEFAULT_SETTINGS, **(project.settings or {})}


async def resolve_project(session, project: Optional[str]) -> Project:
    """Resolve a name-or-id reference to a Project row.

    - None/blank → the Default project (created if missing).
    - UUID string → must exist (404 otherwise — a typo'd id should not
      silently spawn a project named like a UUID).
    - Anything else → get-or-create by name, so `curl -F project=payments`
      works on first use.
    """
    if not project or not project.strip():
        return await _get_or_create_by_name(session, DEFAULT_PROJECT_NAME)

    ref = project.strip()
    try:
        pid = UUID(ref)
    except ValueError:
        return await _get_or_create_by_name(session, ref)

    row = await session.get(Project, pid)
    if row is None:
        raise HTTPException(status_code=404, detail=f"Project {ref} not found")
    return row


async def _get_or_create_by_name(session, name: str) -> Project:
    res = await session.exec(select(Project).where(Project.name == name))
    row = res.first()
    if row is not None:
        return row
    row = Project(name=name)
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return row


# ── Models ───────────────────────────────────────────────────────────────────

class ProjectCreate(BaseModel):
    name: str
    settings: dict[str, Any] = {}


class ProjectUpdate(BaseModel):
    name: Optional[str] = None
    settings: Optional[dict[str, Any]] = None


class ProjectRead(BaseModel):
    id: str
    name: str
    settings: dict[str, Any]
    service_count: int = 0
    created_at: datetime
    updated_at: datetime


class ProjectService(BaseModel):
    name: str
    chunk_count: int
    last_seen: Optional[datetime] = None


# ── Endpoints ────────────────────────────────────────────────────────────────

@router.get("/projects", response_model=List[ProjectRead])
async def list_projects():
    container = get_container()
    async with container.get_session() as session:
        res = await session.exec(select(Project).order_by(Project.created_at))
        projects = list(res.all())
        counts_res = await session.execute(sa_text(
            "SELECT project_id, count(DISTINCT source_service) AS n "
            "FROM log_chunks WHERE project_id IS NOT NULL GROUP BY project_id"
        ))
        counts = {row[0]: row[1] for row in counts_res}
    return [
        ProjectRead(
            id=str(p.id),
            name=p.name,
            settings=effective_settings(p),
            service_count=counts.get(p.id, 0),
            created_at=p.created_at,
            updated_at=p.updated_at,
        )
        for p in projects
    ]


@router.post("/projects", response_model=ProjectRead)
async def create_project(body: ProjectCreate):
    name = body.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Project name must not be empty")
    container = get_container()
    async with container.get_session() as session:
        res = await session.exec(select(Project).where(Project.name == name))
        if res.first() is not None:
            raise HTTPException(status_code=409, detail=f"Project '{name}' already exists")
        p = Project(name=name, settings=body.settings or {})
        session.add(p)
        await session.commit()
        await session.refresh(p)
        return ProjectRead(
            id=str(p.id), name=p.name, settings=effective_settings(p),
            created_at=p.created_at, updated_at=p.updated_at,
        )


@router.get("/projects/{project_id}", response_model=ProjectRead)
async def get_project(project_id: UUID):
    container = get_container()
    async with container.get_session() as session:
        p = await session.get(Project, project_id)
        if p is None:
            raise HTTPException(status_code=404, detail="Project not found")
        return ProjectRead(
            id=str(p.id), name=p.name, settings=effective_settings(p),
            created_at=p.created_at, updated_at=p.updated_at,
        )


@router.patch("/projects/{project_id}", response_model=ProjectRead)
async def update_project(project_id: UUID, body: ProjectUpdate):
    """Partial update; `settings` is merged over existing keys (same
    merge-not-replace contract as PUT /config)."""
    container = get_container()
    async with container.get_session() as session:
        p = await session.get(Project, project_id)
        if p is None:
            raise HTTPException(status_code=404, detail="Project not found")
        if body.name is not None and body.name.strip():
            p.name = body.name.strip()
        if body.settings is not None:
            p.settings = {**(p.settings or {}), **body.settings}
        p.updated_at = datetime.utcnow()
        session.add(p)
        await session.commit()
        await session.refresh(p)
        return ProjectRead(
            id=str(p.id), name=p.name, settings=effective_settings(p),
            created_at=p.created_at, updated_at=p.updated_at,
        )


@router.get("/projects/{project_id}/services", response_model=List[ProjectService])
async def list_project_services(project_id: UUID):
    container = get_container()
    async with container.get_session() as session:
        p = await session.get(Project, project_id)
        if p is None:
            raise HTTPException(status_code=404, detail="Project not found")
        res = await session.execute(sa_text(
            "SELECT source_service, count(*) AS n, max(timestamp_start) AS last_seen "
            "FROM log_chunks WHERE project_id = :pid "
            "GROUP BY source_service ORDER BY n DESC"
        ), {"pid": project_id})
        rows = res.all()
    return [
        ProjectService(name=r[0], chunk_count=r[1], last_seen=r[2])
        for r in rows
    ]
