"""Runtime event clustering over a retrieved chunk set.

The user-visible product framing: "Repi ingests logs, indexes them with
hybrid retrieval, **clusters related events**, builds incident timelines,
and can launch autonomous root-cause investigation." This module is the
**clusters** word in that sentence.

We do not re-run the ingest-time clustering. log_chunks already stores
each row's signature inline in `text` (see log_ingestor.py — the rows are
templated as `"Signature: <sig>\\nExamples: ..."`). We extract the
signature back out, then group the retrieved top-K so the UI can render
"3 events, 1842x · 347x · 92x" instead of 1842 individual log lines.

This is **not** a corpus-wide cluster aggregate — it covers only the
chunks the retrieval pipeline returned for this turn. The UI label must
say so. For a corpus-wide aggregate we would add a /clusters endpoint
with a real `signature` column (Path B in the drift-alignment plan);
that's intentionally deferred.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import List, Optional

logger = logging.getLogger(__name__)


def _extract_signature(chunk_text: str) -> str:
    """Pull the signature back out of the templated chunk body.

    The ingestor writes `"Signature: <sig>\\nExamples: <e1> <e2> ..."`. We
    take the slice between `"Signature: "` and the first newline.

    A chunk without that prefix is dual-source state — external imports or
    pre-ingestor data. Re-running get_signature() over the whole body would
    mask numerics inside the "Examples: ..." portion too, producing a
    signature that doesn't match what the ingestor would have stored for
    the same raw line. That silently mis-clusters. Log instead so we can
    spot the drift, and return empty so the caller skips the chunk.
    """
    if not chunk_text:
        return ""
    prefix = "Signature: "
    if chunk_text.startswith(prefix):
        rest = chunk_text[len(prefix):]
        nl = rest.find("\n")
        return (rest[:nl] if nl != -1 else rest).strip()
    logger.warning(
        "cluster_view: chunk without 'Signature:' prefix — skipping. "
        "Indicates dual-source state (external import or pre-ingestor data).",
    )
    return ""


@dataclass(frozen=True)
class ClusterView:
    signature: str
    count: int
    services: List[str]
    first_ts: Optional[str]
    last_ts: Optional[str]


def cluster_chunks(
    chunks: List[dict],
    min_count: int = 2,
) -> List[ClusterView]:
    """Group `chunks` by extracted signature, drop singletons, return by count desc.

    Each chunk dict is expected in the shape the chat path already produces:
    `{chunk_id, service, level, timestamp, text, ...}`. Timestamps may be ISO
    strings (chat path) or naive — sort behaviour is left to lexical string
    comparison, which is correct for ISO8601.

    `min_count=2` is the default because singletons are already covered by
    the per-turn timeline; surfacing them here would dilute the "compress
    thousands of logs into a few meaningful incidents" framing.
    """
    if not chunks:
        return []

    groups: dict[str, dict] = {}
    for c in chunks:
        sig = _extract_signature(c.get("text") or "")
        if not sig:
            continue
        svc = c.get("service")
        ts = c.get("timestamp")
        g = groups.get(sig)
        if g is None:
            g = {
                "count": 0,
                "services": set(),
                "first_ts": None,
                "last_ts": None,
            }
            groups[sig] = g
        g["count"] += 1
        if svc:
            g["services"].add(svc)
        if ts is not None:
            if g["first_ts"] is None or ts < g["first_ts"]:
                g["first_ts"] = ts
            if g["last_ts"] is None or ts > g["last_ts"]:
                g["last_ts"] = ts

    views: list[ClusterView] = []
    for sig, g in groups.items():
        if g["count"] < min_count:
            continue
        views.append(
            ClusterView(
                signature=sig,
                count=g["count"],
                services=sorted(g["services"]),
                first_ts=g["first_ts"],
                last_ts=g["last_ts"],
            )
        )

    views.sort(key=lambda v: v.count, reverse=True)
    return views
