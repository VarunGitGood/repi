from __future__ import annotations
import logging
from uuid import UUID
from datetime import datetime
from typing import List, Optional, Dict, Any
from sqlmodel import select, desc
from sqlmodel.ext.asyncio.session import AsyncSession
from repi.models.schema import Investigation, InvestigationStep, InvestigationChunk

logger = logging.getLogger(__name__)

class InvestigationStore:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_by_id(self, investigation_id: UUID) -> Optional[Investigation]:
        statement = select(Investigation).where(Investigation.id == investigation_id)
        result = await self.session.exec(statement)
        return result.first()

    async def get_or_create(self, query: str) -> Investigation:
        """Find an existing active investigation for the same query or create a new one."""
        statement = select(Investigation).where(
            Investigation.query == query,
            Investigation.status == "started"
        ).order_by(desc(Investigation.created_at)).limit(1)
        
        result = await self.session.exec(statement)
        investigation = result.first()
        
        if investigation:
            logger.info(f"Resuming existing investigation: {investigation.id}")
            return investigation
            
        return await self.create(query)

    async def create(self, query: str) -> Investigation:
        """Always create a fresh investigation."""
        investigation = Investigation(query=query)
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
        observation: Optional[dict] = None
    ) -> InvestigationStep:
        step = InvestigationStep(
            investigation_id=investigation_id,
            step_number=step_number,
            thought=thought,
            action=action,
            observation=observation
        )
        self.session.add(step)
        
        # Update investigation state
        statement = select(Investigation).where(Investigation.id == investigation_id)
        result = await self.session.exec(statement)
        investigation = result.one()
        investigation.current_step = step_number + 1
        investigation.updated_at = datetime.utcnow()
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
                    try:
                        ts = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                    except (ValueError, TypeError):
                        ts = None
                
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
        investigation.updated_at = datetime.utcnow()
        self.session.add(investigation)
        await self.session.commit()

    async def increment_llm_calls(self, investigation_id: UUID):
        statement = select(Investigation).where(Investigation.id == investigation_id)
        result = await self.session.exec(statement)
        investigation = result.one()
        investigation.total_llm_calls += 1
        self.session.add(investigation)
        await self.session.commit()
