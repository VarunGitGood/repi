import re
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta

def get_signature(message: str) -> str:
    """Mask numbers, hex IDs, and UUIDs to find log signatures."""
    # Mask hex addresses (e.g. 0x123abc)
    message = re.sub(r'0x[0-9a-fA-F]+', '<HEX>', message)
    # Mask UUIDs
    message = re.sub(r'[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}', '<UUID>', message)
    # Mask numbers (version numbers like 1.2.3 might be tricky, but let's keep it simple)
    message = re.sub(r'\d+', '<NUM>', message)
    # Normalize whitespace
    return " ".join(message.split())

def chunk_logs(logs: List[Dict[str, Any]], window_seconds: int = 30) -> List[Dict[str, Any]]:
    """
    Cluster logs by similarity and time window.
    
    Args:
        logs: List of parsed log dictionaries.
        window_seconds: Time window for clustering in seconds.
        
    Returns:
        A list of log clusters (chunks).
    """
    if not logs:
        return []

    clusters = []
    # Sort logs by timestamp if available
    sorted_logs = sorted(logs, key=lambda x: x.get("timestamp") or "")

    current_clusters: Dict[str, Dict[str, Any]] = {}

    for log in sorted_logs:
        message = log.get("message", "")
        signature = get_signature(message)
        ts_str = log.get("timestamp")
        
        try:
            ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00")) if ts_str else None
        except (ValueError, TypeError):
            ts = None

        found = False
        if signature in current_clusters:
            cluster = current_clusters[signature]
            # Check time window
            if ts and cluster["last_ts"]:
                if (ts - cluster["last_ts"]).total_seconds() <= window_seconds:
                    cluster["count"] += 1
                    if len(cluster["examples"]) < 5:
                        cluster["examples"].append(message)
                    cluster["last_ts"] = ts
                    cluster["end_time"] = ts_str or cluster["end_time"]
                    found = True
            elif not ts and not cluster["last_ts"]:
                # If no timestamps, just group by signature
                cluster["count"] += 1
                if len(cluster["examples"]) < 5:
                    cluster["examples"].append(message)
                found = True

        if not found:
            # Create new cluster for this signature
            new_cluster = {
                "signature": signature,
                "count": 1,
                "start_time": ts_str,
                "end_time": ts_str,
                "examples": [message],
                "last_ts": ts
            }
            # For simplicity, we just keep one active cluster per signature
            # In a real system, we'd have multiple windows for the same signature
            # but for this requirement, this is a reasonable simplification.
            if signature in current_clusters:
                # Close the old one and start a new one
                old_cluster = current_clusters[signature]
                old_cluster.pop("last_ts")
                # Format time_range
                s_opt = old_cluster.get("start_time") or "N/A"
                e_opt = old_cluster.get("end_time") or "N/A"
                old_cluster["time_range"] = f"{s_opt} to {e_opt}" if s_opt != e_opt else s_opt
                clusters.append(old_cluster)
            
            current_clusters[signature] = new_cluster

    # Flush remaining clusters
    for cluster in current_clusters.values():
        cluster.pop("last_ts")
        # Format time_range
        start = cluster.get("start_time") or "N/A"
        end = cluster.get("end_time") or "N/A"
        cluster["time_range"] = f"{start} to {end}" if start != end else start
        clusters.append(cluster)

    return clusters
