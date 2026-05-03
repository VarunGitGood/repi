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

def get_signature(message: str) -> str:
    """Mask numbers, hex IDs, and UUIDs to find log signatures."""
    message = re.sub(r'0x[0-9a-fA-F]+', '<HEX>', message)
    message = re.sub(r'[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}', '<UUID>', message)
    message = re.sub(r'\d+', '<NUM>', message)
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
