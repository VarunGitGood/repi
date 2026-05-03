from __future__ import annotations
import json
import re
from typing import Optional, Dict, Any
from datetime import datetime
from dataclasses import dataclass
import logging

logger = logging.getLogger(__name__)

@dataclass
class ParsedLog:
    timestamp: str | None
    level: str
    message: str
    parsed_timestamp: datetime | None = None

# Common log patterns
TEXT_LOG_PATTERN = re.compile(
    r"(?P<timestamp>\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?Z?)?\s*"
    r"\[?(?P<level>INFO|ERROR|WARN|WARNING|DEBUG|CRITICAL|FATAL)\]?\s*"
    r"(?P<message>.*)",
    re.IGNORECASE
)

def _parse_timestamp(ts_str: str | None) -> datetime | None:
    if not ts_str:
        return None
    
    # Try formats
    formats = [
        "%Y-%m-%d %H:%M:%S.%f",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%dT%H:%M:%S.%fZ",
        "%b %d %H:%M:%S" # Syslog
    ]
    
    for fmt in formats:
        try:
            dt = datetime.strptime(ts_str, fmt)
            if fmt == "%b %d %H:%M:%S":
                # Assume current year for syslog
                dt = dt.replace(year=datetime.utcnow().year)
            return dt
        except ValueError:
            continue
            
    # Try ISO format
    try:
        return datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None

def parse_log_line(line: str) -> ParsedLog:
    """
    Parse a single log line into a structured ParsedLog.
    Supports JSON logs and common plain text formats.
    """
    line = line.strip()
    if not line:
        return ParsedLog(timestamp=None, level="INFO", message="")

    # Try parsing as JSON
    try:
        data = json.loads(line)
        ts_str = data.get("timestamp") or data.get("time") or data.get("@timestamp")
        level = str(data.get("level") or data.get("log_level") or "INFO").upper()
        message = data.get("message") or data.get("msg") or line
        return ParsedLog(timestamp=ts_str, level=level, message=message, parsed_timestamp=_parse_timestamp(ts_str))
    except json.JSONDecodeError:
        pass

    # Try parsing as plain text
    match = TEXT_LOG_PATTERN.match(line)
    if match:
        ts_str = match.group("timestamp")
        level = (match.group("level") or "INFO").upper()
        message = match.group("message")
        logger.debug(f"Parser: Matched text log (level={level})")
        return ParsedLog(timestamp=ts_str, level=level, message=message, parsed_timestamp=_parse_timestamp(ts_str))

    # Fallback
    logger.debug("Parser: Falling back to plain message (no match)")
    return ParsedLog(timestamp=None, level="INFO", message=line)
