from __future__ import annotations
import json
import re
from typing import Optional, Dict, Any
from datetime import datetime, timedelta, timezone
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
    r"(?P<timestamp>\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:[.,]\d+)?(?:Z|[+-]\d{2}:?\d{2})?)?\s*-?\s*"
    r"\[?(?P<level>INFO|ERROR|WARN|WARNING|DEBUG|CRITICAL|FATAL)\]?\s*"
    r"(?P<message>.*)",
    re.IGNORECASE
)

# Syslog: "Dec 10 06:55:46 host proc[pid]: message"
SYSLOG_PATTERN = re.compile(
    r"(?P<timestamp>[A-Z][a-z]{2}\s+\d{1,2}\s+\d{2}:\d{2}:\d{2})\s+(?P<message>.+)"
)

# Daemons like sshd prefix some syslog message bodies with a level token
# ("error: maximum authentication attempts exceeded").
SYSLOG_LEVEL_HINT = re.compile(r"(?P<level>error|warning|fatal)\b[: ]", re.IGNORECASE)

# pam_unix/sshd log auth failures at default severity with no level token
# ("authentication failure; logname= ..."). Left as INFO, error-focused
# tools (scan_window) never surface real brute-force incidents.
SYSLOG_FAILURE_HINT = re.compile(r"authentication failure|failed password", re.IGNORECASE)

# Apache/nginx access log: '1.2.3.4 - - [10/Oct/2000:13:55:36 -0700] "GET / HTTP/1.0" 200 ...'
ACCESS_LOG_PATTERN = re.compile(
    r"(?P<host>\S+) \S+ \S+ \[(?P<timestamp>\d{2}/[A-Z][a-z]{2}/\d{4}:\d{2}:\d{2}:\d{2} [+-]\d{4})\] (?P<message>.+)"
)

# Apache error log: '[Sun Dec 04 04:47:44 2005] [error] mod_jk child workerEnv in error state 6'
APACHE_ERROR_PATTERN = re.compile(
    r"\[(?P<timestamp>[A-Z][a-z]{2} [A-Z][a-z]{2} {1,2}\d{1,2} \d{2}:\d{2}:\d{2} \d{4})\] \[(?P<level>[a-z]+)\] (?P<message>.+)"
)

# Apache error-log severities → the level vocabulary the rest of the
# pipeline filters on (INFO/WARNING/ERROR/CRITICAL/DEBUG).
APACHE_LEVEL_MAP = {
    "emerg": "CRITICAL", "alert": "CRITICAL", "crit": "CRITICAL",
    "error": "ERROR", "warn": "WARNING", "notice": "INFO",
    "info": "INFO", "debug": "DEBUG",
}

def _parse_timestamp(ts_str: str | None) -> datetime | None:
    if not ts_str:
        return None

    # Try formats
    formats = [
        "%Y-%m-%d %H:%M:%S.%f",
        "%Y-%m-%d %H:%M:%S,%f",  # log4j / logback
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%dT%H:%M:%S.%fZ",
        "%d/%b/%Y:%H:%M:%S %z",  # apache/nginx access log
        "%a %b %d %H:%M:%S %Y",  # apache error log
        "%b %d %H:%M:%S"  # Syslog
    ]

    dt: datetime | None = None
    for fmt in formats:
        try:
            dt = datetime.strptime(ts_str, fmt)
        except ValueError:
            continue
        if fmt == "%b %d %H:%M:%S":
            # Syslog omits the year — assume the most recent occurrence.
            now = datetime.utcnow()
            dt = dt.replace(year=now.year)
            if dt > now + timedelta(days=1):
                dt = dt.replace(year=now.year - 1)
        break

    if dt is None:
        # Try ISO format
        try:
            dt = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
        except (ValueError, TypeError):
            return None

    # Normalise to naive UTC so timestamps sort/compare consistently downstream.
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt

def parse_log_line(line: str) -> ParsedLog:
    """
    Parse a single log line into a structured ParsedLog.
    Supports JSON logs and common plain text formats
    (ISO/log4j app logs, syslog, apache/nginx access logs).
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

    # Try apache error log ("[Sun Dec 04 04:47:44 2005] [error] message")
    match = APACHE_ERROR_PATTERN.match(line)
    if match:
        ts_str = match.group("timestamp")
        level = APACHE_LEVEL_MAP.get(match.group("level"), "INFO")
        logger.debug(f"Parser: Matched apache error log (level={level})")
        return ParsedLog(timestamp=ts_str, level=level, message=match.group("message"), parsed_timestamp=_parse_timestamp(ts_str))

    # Try syslog ("Dec 10 06:55:46 host sshd[24200]: message")
    match = SYSLOG_PATTERN.match(line)
    if match:
        ts_str = match.group("timestamp")
        message = match.group("message")
        level = "INFO"
        # "host proc[pid]: body" — sniff a leading level token in the body.
        _, sep, body = message.partition(": ")
        hint = SYSLOG_LEVEL_HINT.match(body) if sep else None
        if hint:
            level = hint.group("level").upper()
        elif sep and SYSLOG_FAILURE_HINT.search(body):
            level = "WARNING"
        logger.debug(f"Parser: Matched syslog (level={level})")
        return ParsedLog(timestamp=ts_str, level=level, message=message, parsed_timestamp=_parse_timestamp(ts_str))

    # Try apache/nginx access log
    match = ACCESS_LOG_PATTERN.match(line)
    if match:
        ts_str = match.group("timestamp")
        message = f"{match.group('host')} {match.group('message')}"
        logger.debug("Parser: Matched access log")
        return ParsedLog(timestamp=ts_str, level="INFO", message=message, parsed_timestamp=_parse_timestamp(ts_str))

    # Fallback
    logger.debug("Parser: Falling back to plain message (no match)")
    return ParsedLog(timestamp=None, level="INFO", message=line)
