import os
import hashlib
from datetime import datetime
from typing import List, Optional
from sqlalchemy import create_engine, Column, Integer, String, Float, JSON, DateTime, Boolean
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from lograg.llm.schema import InvestigationResult

Base = declarative_base()

class InvestigationRecord(Base):
    """
    SQLAlchemy model for storing investigation results.
    """
    __tablename__ = "investigations"

    id = Column(Integer, primary_key=True)
    title = Column(String, nullable=False)
    title_hash = Column(String, unique=True, nullable=False)
    summary = Column(String)
    root_cause = Column(String)
    confidence = Column(Float)
    impact = Column(JSON)
    affected_services = Column(JSON)
    reproduction_steps = Column(JSON)
    should_create_issue = Column(Boolean)
    created_at = Column(DateTime, default=datetime.utcnow)

class DatabaseManager:
    """
    Manager for SQLite storage.
    """
    def __init__(self, db_path: str = "data/lograg.db"):
        """
        Initialize the database.
        6543
        Args:
            db_path: Path to the SQLite database file.
        """
        if db_path != ":memory:":
            os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
            self.engine = create_engine(f"sqlite:///{db_path}")
        else:
            self.engine = create_engine("sqlite:///:memory:")
            
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)

    def _get_hash(self, text: str) -> str:
        """Generate a SHA-256 hash of the text."""
        return hashlib.sha256(text.lower().strip().encode()).hexdigest()

    def save_investigation(self, result: InvestigationResult) -> None:
        """
        Save an investigation result to the database.
        
        Args:
            result: The InvestigationResult to save.
        """
        session = self.Session()
        try:
            title_hash = self._get_hash(result.title)
            
            # Check if it already exists
            existing = session.query(InvestigationRecord).filter_by(title_hash=title_hash).first()
            if existing:
                # Update existing record
                existing.summary = result.summary
                existing.root_cause = result.root_cause
                existing.confidence = result.confidence
                existing.impact = result.impact
                existing.affected_services = result.affected_services
                existing.reproduction_steps = result.reproduction_steps
                existing.should_create_issue = result.should_create_issue
                existing.created_at = datetime.utcnow()
            else:
                # Create new record
                record = InvestigationRecord(
                    title=result.title,
                    title_hash=title_hash,
                    summary=result.summary,
                    root_cause=result.root_cause,
                    confidence=result.confidence,
                    impact=result.impact,
                    affected_services=result.affected_services,
                    reproduction_steps=result.reproduction_steps,
                    should_create_issue=result.should_create_issue
                )
                session.add(record)
            session.commit()
        except Exception as e:
            session.rollback()
            raise e
        finally:
            session.close()

    def find_similar(self, title: str) -> Optional[InvestigationRecord]:
        """
        Find an existing investigation with a similar title.
        
        Args:
            title: The title to search for.
            
        Returns:
            The InvestigationRecord if found, else None.
        """
        session = self.Session()
        try:
            title_hash = self._get_hash(title)
            record = session.query(InvestigationRecord).filter_by(title_hash=title_hash).first()
            return record
        finally:
            session.close()
