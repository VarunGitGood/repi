"""GET /conversations + GET /conversations/{id}.

The sidebar lists conversations ordered by `updated_at`. Clicking one returns
chat turns and investigations interleaved chronologically, each carrying a
`mode` discriminator so the UI can pick the right component to render.
"""
from __future__ import annotations

import logging
from typing import List
from uuid import UUID

from fastapi import APIRouter, HTTPException
from sqlmodel import select

from repi.core.container import get_container
from repi.models.schema import ChatMessage, Conversation, Investigation, Project
from repi.api.schemas import ConversationDetail, ConversationSummary, TranscriptTurn

logger = logging.getLogger("repi.api.conversations")

router = APIRouter()


@router.get("/conversations", response_model=List[ConversationSummary])
async def list_conversations(limit: int = 50):
    container = get_container()
    async with container.async_session_maker() as session:
        stmt = (
            select(Conversation)
            .order_by(Conversation.updated_at.desc())
            .limit(limit)
        )
        res = await session.exec(stmt)
        rows = list(res.all())
        name_res = await session.exec(select(Project.id, Project.name))
        project_names = {pid: name for pid, name in name_res.all()}
    return [
        ConversationSummary(
            id=str(c.id),
            title=c.title,
            project_id=str(c.project_id) if c.project_id else None,
            project_name=project_names.get(c.project_id),
            created_at=c.created_at.isoformat(),
            updated_at=c.updated_at.isoformat(),
        )
        for c in rows
    ]


@router.get("/conversations/{conversation_id}", response_model=ConversationDetail)
async def get_conversation(conversation_id: str):
    try:
        cid = UUID(conversation_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid conversation id")

    container = get_container()
    async with container.async_session_maker() as session:
        conv_res = await session.exec(select(Conversation).where(Conversation.id == cid))
        conv = conv_res.first()
        if conv is None:
            raise HTTPException(status_code=404, detail="Conversation not found")

        project_name = None
        if conv.project_id is not None:
            proj = await session.get(Project, conv.project_id)
            project_name = proj.name if proj else None

        msg_res = await session.exec(
            select(ChatMessage)
            .where(ChatMessage.conversation_id == cid)
            .order_by(ChatMessage.created_at)
        )
        chat_msgs = list(msg_res.all())

        inv_res = await session.exec(
            select(Investigation)
            .where(Investigation.conversation_id == cid)
            .order_by(Investigation.created_at)
        )
        investigations = list(inv_res.all())

    # Interleave chronologically. Each row carries a `mode` so the UI knows
    # whether to render a ChatMessage component or an InvestigationStep view.
    turns: List[TranscriptTurn] = []
    for m in chat_msgs:
        turns.append(TranscriptTurn(
            mode="chat",
            id=str(m.id),
            role=m.role,
            content=m.content,
            chunk_ids=list(m.chunk_ids or []),
            confidence=m.confidence,
            created_at=m.created_at.isoformat(),
        ))
    for inv in investigations:
        turns.append(TranscriptTurn(
            mode="investigate",
            id=str(inv.id),
            content=inv.query,  # the user's prompt that started the investigation
            confidence=None,
            status=inv.status,
            created_at=inv.created_at.isoformat(),
        ))
    turns.sort(key=lambda t: t.created_at)

    return ConversationDetail(
        id=str(conv.id),
        title=conv.title,
        project_id=str(conv.project_id) if conv.project_id else None,
        project_name=project_name,
        created_at=conv.created_at.isoformat(),
        updated_at=conv.updated_at.isoformat(),
        turns=turns,
    )
