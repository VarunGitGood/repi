"""Service-stratified diversification for hybrid search results.

The fix is for one specific failure mode: when a query like "why are payments
failing" returns a top-K dominated by a single noisy service (e.g. 9 of 10
from auth-service), the downstream timeline and event-clusters views collapse
into a single-service narrative. The query was *about* a cross-service
incident; the retrieval erased the cross-service signal.

This is NOT embedding-MMR (which would need candidate embeddings and a second
DB roundtrip). It's a service-aware greedy reshuffle: walk the ranked
candidates in order, but skip any candidate whose source_service has already
hit a per-service cap, and only reconsider skipped candidates once the pool
of under-represented services is exhausted.

If the candidate pool is monolithic in service (filters pinned it, or that's
genuinely all the corpus has), the function is a no-op.
"""
from __future__ import annotations
from typing import List, Dict, Any
import logging
import math

logger = logging.getLogger(__name__)


def diversify_by_service(
    candidates: List[Dict[str, Any]],
    top_k: int,
    cap_ratio: float = 0.4,
    service_key: str = "service",
) -> List[Dict[str, Any]]:
    """Reorder `candidates` so no single service occupies more than
    `ceil(top_k * cap_ratio)` of the returned top-K.

    `candidates` is assumed pre-sorted by relevance (highest first). Each
    dict carries `service_key`. The function preserves the relative order
    *within* each service, only demoting cross-service.

    Returns at most `top_k` items. If `candidates` is shorter than `top_k`,
    returns everything (still diversified).
    """
    if top_k <= 1 or not candidates:
        return candidates[:top_k]

    per_service_cap = max(1, math.ceil(top_k * cap_ratio))

    picked: List[Dict[str, Any]] = []
    deferred: List[Dict[str, Any]] = []
    counts: Dict[str, int] = {}

    for c in candidates:
        if len(picked) >= top_k:
            break
        svc = c.get(service_key) or "__unknown__"
        if counts.get(svc, 0) < per_service_cap:
            picked.append(c)
            counts[svc] = counts.get(svc, 0) + 1
        else:
            deferred.append(c)

    # If we couldn't fill top_k from the cap-respecting pass (e.g. only one
    # service in the candidate pool), fall back to the deferred queue in
    # original order. The cap is a soft preference, not a hard ceiling.
    if len(picked) < top_k and deferred:
        room = top_k - len(picked)
        logger.debug(
            "diversify_by_service: cap unmet, backfilling %d from deferred", room
        )
        picked.extend(deferred[:room])

    return picked
