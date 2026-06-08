from __future__ import annotations
import logging
from uuid import UUID
from typing import List, Optional, Dict, Any
from sqlmodel import select, desc
from sqlmodel.ext.asyncio.session import AsyncSession
from repi.core.dates import DateHandler, default_date_handler as _dh
from repi.models.schema import Investigation, InvestigationStep, InvestigationChunk

logger = logging.getLogger(__name__)

class InvestigationStore:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_by_id(self, investigation_id: UUID) -> Optional[Investigation]:
        statement = select(Investigation).where(Investigation.id == investigation_id)
        result = await self.session.exec(statement)
        return result.first()

    async def list_all(self, limit: int = 50) -> List[Investigation]:
        """List all investigations, newest first."""
        statement = select(Investigation).order_by(desc(Investigation.created_at)).limit(limit)
        result = await self.session.exec(statement)
        return list(result.all())

    async def get_or_create(
        self,
        query: str,
        conversation_id: Optional[UUID] = None,
    ) -> Investigation:
        """Find an existing active investigation for the same (query, conversation)
        or create a new one. Same query in a *different* conversation creates a
        fresh investigation — investigations are conversation-scoped."""
        statement = select(Investigation).where(
            Investigation.query == query,
            Investigation.status == "started",
            Investigation.conversation_id == conversation_id,
        ).order_by(desc(Investigation.created_at)).limit(1)

        result = await self.session.exec(statement)
        investigation = result.first()

        if investigation:
            logger.info(f"Resuming existing investigation: {investigation.id}")
            return investigation

        return await self.create(query, conversation_id=conversation_id)

    async def create(
        self,
        query: str,
        conversation_id: Optional[UUID] = None,
    ) -> Investigation:
        """Always create a fresh investigation."""
        investigation = Investigation(query=query, conversation_id=conversation_id)
        self.session.add(investigation)
        await self.session.commit()
        await self.session.refresh(investigation)
        logger.info(f"Created new investigation: {investigation.id}")
        return investigation

    async def get_steps(self, investigation_id: UUID) -> List[InvestigationStep]:
        statement = select(InvestigationStep).where(
            InvestigationStep.investigation_id == investigation_id
        ).order_by(InvestigationStep.step_number)
        result = await self.session.exec(statement)
        return list(result.all())

    async def add_step(
        self,
        investigation_id: UUID,
        step_number: int,
        thought: str,
        action: Optional[dict] = None,
        observation: Optional[dict] = None,
        kind: Optional[str] = None,
    ) -> InvestigationStep:
        step = InvestigationStep(
            investigation_id=investigation_id,
            step_number=step_number,
            thought=thought,
            action=action,
            observation=observation,
            kind=kind,
        )
        self.session.add(step)

        statement = select(Investigation).where(Investigation.id == investigation_id)
        result = await self.session.exec(statement)
        investigation = result.one()
        investigation.current_step = step_number + 1
        investigation.updated_at = _dh.now()
        self.session.add(investigation)
        
        await self.session.commit()
        return step

    async def add_chunks(self, investigation_id: UUID, chunks: List[dict]):
        """Deduplicate and store evidence chunks."""
        statement = select(InvestigationChunk.chunk_id).where(
            InvestigationChunk.investigation_id == investigation_id
        )
        result = await self.session.exec(statement)
        existing_ids = set(result.all())
        
        for c in chunks:
            cid = c.get("chunk_id")
            if cid and cid not in existing_ids:
                ts = c.get("timestamp_start") or c.get("timestamp")
                if isinstance(ts, str):
                    ts = DateHandler.parse_iso(ts)
                
                chunk = InvestigationChunk(
                    investigation_id=investigation_id,
                    chunk_id=cid,
                    service=c.get("service") or c.get("source_service"),
                    timestamp=ts,
                    message=c.get("text")
                )
                self.session.add(chunk)
                existing_ids.add(cid)
        
        await self.session.commit()

    async def get_chunks(self, investigation_id: UUID) -> List[InvestigationChunk]:
        statement = select(InvestigationChunk).where(
            InvestigationChunk.investigation_id == investigation_id
        )
        result = await self.session.exec(statement)
        return list(result.all())

    async def finalize(self, investigation_id: UUID, answer: str, status: str = "completed"):
        statement = select(Investigation).where(Investigation.id == investigation_id)
        result = await self.session.exec(statement)
        investigation = result.one()
        investigation.answer = answer
        investigation.status = status
        investigation.updated_at = _dh.now()
        self.session.add(investigation)
        await self.session.commit()

    async def increment_llm_calls(self, investigation_id: UUID):
        statement = select(Investigation).where(Investigation.id == investigation_id)
        result = await self.session.exec(statement)
        investigation = result.one()
        investigation.total_llm_calls += 1
        self.session.add(investigation)
        await self.session.commit()

    async def set_awaiting_clarification(self, investigation_id: UUID, question: str) -> None:
        """Set investigation status to awaiting_clarification with a pending question."""
        inv = await self.get_by_id(investigation_id)
        if inv:
            inv.status = "awaiting_clarification"
            inv.pending_question = question
            self.session.add(inv)
            await self.session.commit()

    async def resume_from_clarification(self, investigation_id: UUID, reply: str) -> None:
        """Write user's reply as observation on the pending ask_user step, then set status=running."""
        steps = await self.get_steps(investigation_id)
        ask_user_step = next(
            (s for s in reversed(steps) if s.action and s.action.get("name") == "ask_user" and not s.observation),
            None
        )
        if ask_user_step:
            ask_user_step.observation = {"tool_name": "ask_user", "args": {}, "result": {"reply": reply}}
            self.session.add(ask_user_step)

        inv = await self.get_by_id(investigation_id)
        if inv:
            inv.status = "running"
            inv.pending_question = None
            self.session.add(inv)

        await self.session.commit()
