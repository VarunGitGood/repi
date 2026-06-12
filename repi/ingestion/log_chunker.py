from __future__ import annotations
import re
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta
from dataclasses import dataclass
import logging
from repi.ingestion.log_parser import ParsedLog

logger = logging.getLogger(__name__)

@dataclass
class ChunkedLog:
    signature: str
    count: int
    examples: List[str]
    timestamp_start: datetime | None
    timestamp_end: datetime | None
    time_range: str
    log_level: str = "INFO"

_IPV4_RE = re.compile(r'\b\d{1,3}(?:\.\d{1,3}){3}\b')
_NUM_RE = re.compile(r'\d+')
# Context immediately before a 3-digit number that marks it as an HTTP status
# code ('status 404', 'code=502', '"GET / HTTP/1.1" 200').
_STATUS_CTX = re.compile(r'(?:status|code|http)[^a-zA-Z]{0,8}$', re.IGNORECASE)
# Protocol/version digits ('HTTP/1.1') — low-cardinality, keep readable.
_HTTP_VERSION_CTX = re.compile(r'http/[\d.]*$', re.IGNORECASE)

def get_signature(message: str) -> str:
    """Mask high-cardinality tokens (hex IDs, UUIDs, IPs, numbers) to find log
    signatures. Low-cardinality numbers that carry meaning are preserved:
    HTTP status codes, protocol versions, and short digit runs inside
    identifiers (jk2_init, utf8_decode) — masking those splits or mislabels
    clusters without reducing cardinality."""
    message = re.sub(r'0x[0-9a-fA-F]+', '<HEX>', message)
    message = re.sub(r'[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}', '<UUID>', message)
    message = _IPV4_RE.sub('<IP>', message)

    def _mask(m: re.Match) -> str:
        tok = m.group()
        s, start, end = m.string, m.start(), m.end()
        # Mid-identifier digits followed by more identifier chars (jk2_init).
        # Trailing digits (node1, worker23) still mask so per-instance names
        # collapse into one cluster.
        if len(tok) <= 3 and start > 0 and s[start - 1].isalpha() \
                and end < len(s) and (s[end].isalpha() or s[end] == '_'):
            return tok
        prefix = s[max(0, start - 12):start]
        if _HTTP_VERSION_CTX.search(prefix):
            return tok
        if len(tok) == 3 and tok[0] in '12345' and _STATUS_CTX.search(prefix):
            return tok
        return '<NUM>'

    message = _NUM_RE.sub(_mask, message)
    return " ".join(message.split())

def chunk_logs(logs: List[ParsedLog], window_seconds: int = 30) -> List[ChunkedLog]:
    """Cluster logs by similarity and time window."""
    if not logs:
        return []

    clusters = []
    # Sort logs by timestamp if available
    sorted_logs = sorted(logs, key=lambda x: x.parsed_timestamp or datetime.min)

    current_clusters: Dict[str, Dict[str, Any]] = {}

    for log in sorted_logs:
        signature = get_signature(log.message)
        ts = log.parsed_timestamp

        found = False
        if signature in current_clusters:
            cluster = current_clusters[signature]
            if ts and cluster["last_ts"]:
                if (ts - cluster["last_ts"]).total_seconds() <= window_seconds:
                    cluster["count"] += 1
                    if len(cluster["examples"]) < 5:
                        cluster["examples"].append(log.message)
                    cluster["last_ts"] = ts
                    cluster["timestamp_end"] = ts
                    found = True
            elif not ts and not cluster["last_ts"]:
                cluster["count"] += 1
                if len(cluster["examples"]) < 5:
                    cluster["examples"].append(log.message)
                found = True
            
            if found:
                logger.debug(f"Chunker: Added log to cluster '{signature}'")

        if not found:
            logger.debug(f"Chunker: Creating new cluster for '{signature}'")
            if signature in current_clusters:
                # Flush old cluster
                old = current_clusters[signature]
                clusters.append(ChunkedLog(
                    signature=old["signature"],
                    count=old["count"],
                    examples=old["examples"],
                    timestamp_start=old["timestamp_start"],
                    timestamp_end=old["timestamp_end"],
                    time_range=f"{old['timestamp_start']} to {old['timestamp_end']}" if old["timestamp_start"] else "N/A",
                    log_level=old["log_level"]
                ))
            
            current_clusters[signature] = {
                "signature": signature,
                "count": 1,
                "examples": [log.message],
                "timestamp_start": ts,
                "timestamp_end": ts,
                "last_ts": ts,
                "log_level": log.level
            }

    # Flush remaining
    for old in current_clusters.values():
        clusters.append(ChunkedLog(
            signature=old["signature"],
            count=old["count"],
            examples=old["examples"],
            timestamp_start=old["timestamp_start"],
            timestamp_end=old["timestamp_end"],
            time_range=f"{old['timestamp_start']} to {old['timestamp_end']}" if old["timestamp_start"] else "N/A",
            log_level=old["log_level"]
        ))

    return clusters
