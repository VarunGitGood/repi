from __future__ import annotations
import re
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional, Tuple
from src.app.retrieval.rrf import RRFRetrievalService
from src.app.models.filters import RetrievalFilters

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

def extract_time_range(query: str, now: datetime) -> Optional[tuple[datetime, datetime]]:
    """
    Extracts time hints from query (e.g., 'since 02:31', 'last 2 hours').
    Returns (start, end) or None.
    """
    query_lower = query.lower()
    
    # Simple regex for "since HH:MM"
    since_match = re.search(r"since (\d{1,2}):(\d{2})", query_lower)
    if since_match:
        hh, mm = map(int, since_match.groups())
        # Assume same day (or handle midnight cross if needed)
        start = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
        if start > now:
            start -= timedelta(days=1)
        return (start - timedelta(minutes=5), start + timedelta(minutes=15))

    # "last X hours"
    last_h_match = re.search(r"last (\d+) hours?", query_lower)
    if last_h_match:
        hours = int(last_h_match.group(1))
        return (now - timedelta(hours=hours), now)

    return None

async def progressive_search(
    retrieval_service: RRFRetrievalService,
    query: str,
    now: datetime,
    service: str | None = None,
    limit: int = 5
) -> list[dict]:
    """
    Implements 1h -> 3h -> 6h -> 24h progressive search sequence.
    """
    windows = [1, 3, 6, 24]
    
    for hours in windows:
        logger.info(f"Progressive search: trying last {hours}h window")
        time_from = now - timedelta(hours=hours)
        filters = RetrievalFilters(
            source_service=service,
            time_from=time_from,
            time_to=now
        )
        
        # We use a larger k internally to find clusters
        results = await retrieval_service.search(query=query, top_k=20, filters=filters)
        if not results:
            continue
            
        # Enrich and cluster
        chunk_ids = [res[0] for res in results]
        chunks_data = await retrieval_service.vector_store.get_chunks_by_ids(chunk_ids)
        
        enriched = []
        for cid, score in results:
            data = chunks_data.get(cid, {})
            enriched.append({
                "chunk_id": cid,
                "timestamp": data.get("timestamp_start"),
                "source_service": data.get("source_service"),
                "log_level": data.get("log_level"),
                "text": data.get("text"),
                "score": score
            })
            
        # If we have meaningful signal, cluster and return
        if enriched:
            clustered = cluster_logs(enriched)
            if clustered:
                return clustered
                
    return []
