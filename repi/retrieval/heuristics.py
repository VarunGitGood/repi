from __future__ import annotations
import re
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional, Tuple
from repi.retrieval.rrf import RRFRetrievalService
from repi.models.filters import RetrievalFilters

logger = logging.getLogger(__name__)

def cluster_logs(logs: list[dict], window_min: int = 2) -> list[dict]:
    """
    Groups logs into clusters where the gap between consecutive logs is < window_min.
    Returns logs from the densest cluster (max 5).
    """
    if not logs:
        return []

    # Sort logs by timestamp (ensure they have timestamp)
    processed_logs = []
    for log in logs:
        ts = log.get("timestamp_start") or log.get("timestamp")
        if isinstance(ts, str):
            try:
                ts = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            except ValueError:
                continue
        if not ts:
            continue
        processed_logs.append((ts, log))
    
    processed_logs.sort(key=lambda x: x[0])

    if not processed_logs:
        return []

    clusters = []
    current_cluster = [processed_logs[0]]

    for i in range(1, len(processed_logs)):
        prev_ts, _ = processed_logs[i-1]
        curr_ts, curr_log = processed_logs[i]
        
        if (curr_ts - prev_ts).total_seconds() <= window_min * 60:
            current_cluster.append((curr_ts, curr_log))
        else:
            clusters.append(current_cluster)
            current_cluster = [(curr_ts, curr_log)]
    clusters.append(current_cluster)

    # Find the densest cluster (most logs)
    densest = max(clusters, key=len)
    
    # Return max 5 logs from this cluster
    return [item[1] for item in densest[:5]]

