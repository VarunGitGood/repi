from typing import List, Dict
from pydantic import BaseModel, Field

class InvestigationResult(BaseModel):
    """
    Pydantic model for the structured LLM-based investigation result.
    """
    title: str = Field(..., description="A concise title for the investigation")
    summary: str = Field(..., description="A high-level summary of the findings")
    root_cause: str = Field(..., description="The identified root cause of the log pattern")
    confidence: float = Field(..., description="Confidence score between 0 and 1", ge=0.0, le=1.0)
    impact: Dict[str, str] = Field(..., description="Impact analysis (e.g., {'severity': 'high', 'user_impact': '...'})")
    affected_services: List[str] = Field(..., description="List of services or components affected")
    reproduction_steps: List[str] = Field(..., description="Steps to reproduce the issue")
    should_create_issue: bool = Field(..., description="Whether a GitHub issue should be created")
