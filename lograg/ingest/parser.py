import json
import re
from typing import Optional, Dict, Any
from datetime import datetime

# Common log patterns
TEXT_LOG_PATTERN = re.compile(
    r"(?P<timestamp>\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?Z?)?\s*"
    r"\[?(?P<level>INFO|ERROR|WARNING|DEBUG|CRITICAL|FATAL)\]?\s*"
    r"(?P<message>.*)",
    re.IGNORECASE
)

def parse_log_line(line: str) -> Dict[str, Any]:
    """
    Parse a single log line into a structured dictionary.
    
    Supports JSON logs and common plain text formats.
    
    Args:
        line: The raw log line string.
        
    Returns:
        A dictionary with 'timestamp', 'level', and 'message'.
    """
    line = line.strip()
    if not line:
        return {}

    # Try parsing as JSON
    try:
        data = json.loads(line)
        return {
            "timestamp": data.get("timestamp") or data.get("time") or data.get("@timestamp"),
            "level": str(data.get("level") or data.get("log_level") or "INFO").upper(),
            "message": data.get("message") or data.get("msg") or line
        }
    except json.JSONDecodeError:
        pass

    # Try parsing as plain text
    match = TEXT_LOG_PATTERN.match(line)
    if match:
        return {
            "timestamp": match.group("timestamp"),
            "level": (match.group("level") or "INFO").upper(),
            "message": match.group("message")
        }

    # Fallback
    return {
        "timestamp": None,
        "level": "INFO",
        "message": line
    }
