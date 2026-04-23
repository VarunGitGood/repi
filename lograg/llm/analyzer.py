import os
import json
import logging
from typing import List, Dict, Any
from dotenv import load_dotenv
from llama_index.llms.openai import OpenAI
from lograg.llm.schema import InvestigationResult
from lograg.llm.prompts import INVESTIGATION_PROMPT

# Suppress NLTK and LlamaIndex logging
logging.getLogger("nltk").setLevel(logging.ERROR)
logging.getLogger("llama_index").setLevel(logging.ERROR)

# Silence NLTK downloader
try:
    import nltk
    nltk.download('punkt', quiet=True)
    nltk.download('punkt_tab', quiet=True)
except ImportError:
    pass

load_dotenv()

class LLMAnalyzer:
    """
    LLM-based log analyzer using LlamaIndex and OpenAI.
    """
    def __init__(self, model: str = "gpt-4o"):
        """
        Initialize the LLM analyzer.
        
        Args:
            model: OpenAI model name.
        """
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise ValueError("OPENAI_API_KEY environment variable is not set")
        
        self.llm = OpenAI(model=model, api_key=api_key)

    def analyze(self, query: str, evidence: List[Dict[str, Any]]) -> InvestigationResult:
        """
        Analyze log clusters and return a structured investigation result.
        
        Args:
            query: The initial investigation query.
            evidence: List of log clusters.
            
        Returns:
            An InvestigationResult object.
        """
        # Format evidence as JSON string
        evidence_str = json.dumps(evidence, indent=2)
        
        # Format prompt
        prompt = INVESTIGATION_PROMPT.format(query=query, evidence=evidence_str)
        
        # Call LLM
        response = self.llm.complete(prompt)
        content = response.text.strip()
        
        # Robust JSON parsing
        try:
            # Try to find JSON block if model wrapped it in markdown
            if "```json" in content:
                content = content.split("```json")[-1].split("```")[0].strip()
            elif "```" in content:
                content = content.split("```")[-1].split("```")[0].strip()
                
            data = json.loads(content)
            return InvestigationResult(**data)
        except (json.JSONDecodeError, ValueError) as e:
            # Fallback or re-raise
            # In a production system, you might want to retry or use a more robust parser
            print(f"Error parsing LLM response: {e}")
            print(f"Raw content: {content}")
            
            # Simple fallback if possible
            return InvestigationResult(
                title="Investigation Failed",
                summary=f"Failed to parse LLM output: {str(e)}",
                root_cause="Parsing Error",
                confidence=0.0,
                impact={"severity": "unknown", "description": "N/A"},
                affected_services=[],
                reproduction_steps=[],
                should_create_issue=False
            )
