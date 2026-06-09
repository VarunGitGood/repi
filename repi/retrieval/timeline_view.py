"""Build a user-facing timeline from a retrieved chunk set.

The user-visible product framing: "Repi ingests logs, indexes them with
hybrid retrieval, clusters related events, **builds incident timelines**,
and can launch autonomous root-cause investigation." This module is the
**timelines** word in that sentence.

Unlike repi.investigation.tools.get_timeline (an internal ReAct tool that
takes chunk_ids and does a SELECT), this runs over the chunks the chat
path already hydrated — no second DB roundtrip. The output is a
chronologically ordered, run-collapsed view: adjacent rows with the same
(service, level, signature) become one entry carrying `repeat_count` and
a `first_ts` / `last_ts` range, so the UI shows "auth-service ERROR x12
14:02–14:04" instead of twelve near-identical lines.

Signature extraction reuses cluster_view.extract_signature to pull the
templated `text` body apart — the ingestor stores rows as
`"Signature: <sig>\\nExamples: ..."` (see log_ingestor.py).
"""
from __future__ import annotations

import logging
from typing import List, Optional, TypedDict

from repi.retrieval.cluster_view import extract_signature

logger = logging.getLogger(__name__)


class TimelineEntry(TypedDict):
    service: Optional[str]
    level: Optional[str]
    signature: str
    first_ts: str
    last_ts: str
    repeat_count: int


def build_timeline(chunks: List[dict]) -> List[TimelineEntry]:
    """Project `chunks` to a chronological, run-collapsed timeline.

    Each input dict is expected in the shape the chat path produces:
    `{chunk_id, service, level, timestamp, text, ...}`. Chunks without a
    timestamp are dropped — placing them in chronological order would
    require fabricating a position, and a "where exactly" question is
    what a timeline answers. ISO8601 strings sort lexically correctly,
    which is what `_dh.to_iso` already produces upstream.

    Collapsing is on identical (service, level, signature). Two ERROR
    hits and one INFO hit with the same signature stay separate — they
    are different events for the human reader.
    """
    timestamped = [c for c in chunks if c.get("timestamp")]
    if not timestamped:
        return []

    ordered = sorted(timestamped, key=lambda c: c["timestamp"])

    entries: list[TimelineEntry] = []
    skipped = 0
    for c in ordered:
        sig = extract_signature(c.get("text") or "")
        if not sig:
            # No signature → can't form a run key, can't render meaningfully.
            # Tally so a spike in untemplated chunks shows up in logs (signals
            # ingest drift or external import contamination).
            skipped += 1
            continue
        service = c.get("service")
        level = c.get("level")
        ts = c["timestamp"]

        if entries:
            last = entries[-1]
            if (
                last["service"] == service
                and last["level"] == level
                and last["signature"] == sig
            ):
                # Same run — extend the range, bump the counter.
                last["last_ts"] = ts
                last["repeat_count"] += 1
                continue

        entries.append(
            TimelineEntry(
                service=service,
                level=level,
                signature=sig,
                first_ts=ts,
                last_ts=ts,
                repeat_count=1,
            )
        )

    if skipped:
        logger.debug(
            "build_timeline: skipped %d chunk(s) without a signature", skipped
        )
    return entries
