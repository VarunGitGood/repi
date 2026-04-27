from __future__ import annotations
import re
from dataclasses import dataclass
from datetime import datetime, timedelta

@dataclass
class ParsedIntent:
    source_service: str | None      # extracted service name
    log_level: str | None           # ERROR, WARNING, INFO, DEBUG
    time_from: datetime | None
    time_to: datetime | None
    clean_query: str                # original query with extracted tokens removed

def parse_intent(query: str, known_services: list[str]) -> ParsedIntent:
    """
    Parse a natural language query to extract structured intent.
    Implement with regex and string matching, no LLM.
    """
    clean_query = query
    source_service = None
    log_level = None
    time_from = None
    time_to = None
    now = datetime.utcnow()

    # 1. Service extraction
    for service in known_services:
        pattern = re.compile(rf"\b{re.escape(service)}\b", re.IGNORECASE)
        if pattern.search(clean_query):
            source_service = service
            clean_query = pattern.sub("", clean_query)
            break

    # 2. Log level extraction
    level_pattern = re.compile(r"\b(ERROR|WARNING|WARN|INFO|DEBUG|CRITICAL)\b", re.IGNORECASE)
    level_match = level_pattern.search(clean_query)
    if level_match:
        log_level = level_match.group(1).upper()
        if log_level == "WARN":
            log_level = "WARNING"
        clean_query = level_pattern.sub("", clean_query)

    # 3. Time ranges
    # "last N minutes" / "last N min"
    min_match = re.search(r"last (\d+) (minutes|min)", clean_query, re.IGNORECASE)
    if min_match:
        time_from = now - timedelta(minutes=int(min_match.group(1)))
        clean_query = re.sub(min_match.group(0), "", clean_query, flags=re.IGNORECASE)

    # "last N hours" / "last N h"
    hour_match = re.search(r"last (\d+) (hours|h)", clean_query, re.IGNORECASE)
    if hour_match:
        time_from = now - timedelta(hours=int(hour_match.group(1)))
        clean_query = re.sub(hour_match.group(0), "", clean_query, flags=re.IGNORECASE)

    # "last N days"
    day_match = re.search(r"last (\d+) days", clean_query, re.IGNORECASE)
    if day_match:
        time_from = now - timedelta(days=int(day_match.group(1)))
        clean_query = re.sub(day_match.group(0), "", clean_query, flags=re.IGNORECASE)

    # "today"
    if re.search(r"\btoday\b", clean_query, re.IGNORECASE):
        time_from = now.replace(hour=0, minute=0, second=0, microsecond=0)
        clean_query = re.sub(r"\btoday\b", "", clean_query, flags=re.IGNORECASE)

    # "yesterday"
    if re.search(r"\byesterday\b", clean_query, re.IGNORECASE):
        yesterday = now - timedelta(days=1)
        time_from = yesterday.replace(hour=0, minute=0, second=0, microsecond=0)
        time_to = time_from + timedelta(days=1)
        clean_query = re.sub(r"\byesterday\b", "", clean_query, flags=re.IGNORECASE)

    # Cleanup query
    clean_query = " ".join(clean_query.split())
    
    return ParsedIntent(
        source_service=source_service,
        log_level=log_level,
        time_from=time_from,
        time_to=time_to,
        clean_query=clean_query
    )
