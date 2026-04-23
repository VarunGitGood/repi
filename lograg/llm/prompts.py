from llama_index.core import PromptTemplate

INVESTIGATION_PROMPT = PromptTemplate(
    "You are an expert site reliability engineer. Your task is to investigate log patterns and decide if they warrant a GitHub issue.\n\n"
    "QUERY: {query}\n\n"
    "LOG EVIDENCE (CLUSTERS):\n"
    "{evidence}\n\n"
    "Based on the log evidence provided above, please perform a structured investigation.\n"
    "Identify the failure pattern, estimate impact, suggest a root cause, and generate reproduction steps.\n\n"
    "You MUST return a STRICT JSON object matching the following schema:\n"
    "{{\n"
    '  "title": "Concise investigation title",\n'
    '  "summary": "High-level summary of findings",\n'
    '  "root_cause": "Identified root cause",\n'
    '  "confidence": 0.0 to 1.0,\n'
    '  "impact": {{"severity": "low/medium/high", "description": "..."}},\n'
    '  "affected_services": ["service1", "service2"],\n'
    '  "reproduction_steps": ["step1", "step2"],\n'
    '  "should_create_issue": true/false\n'
    "}}\n\n"
    "JSON OUTPUT:"
)
