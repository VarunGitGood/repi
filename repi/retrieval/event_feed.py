"""Heuristic timeline events for the project overview (UX redesign P2).

The landing page answers "what happened recently?" with EVENTS, not raw
logs: "JWT verification failures begin", "checkout retries spike (×340)",
"auth-service enters degraded state". Events are derived deterministically
from per-(service, signature) time-bucket aggregates — no LLM call, so the
overview is free and instant to load.

Split into a SQL fetch (`fetch_window_aggregates`) and a pure rule engine
(`derive_events`) so the rules are unit-testable without a database.

Rules (per error-class (service, signature) series over N buckets):
- begins:      first active bucket has count ≥ BEGINS_MIN and the previous
               bucket was quiet (skipped when the series is already active
               at the window edge — we didn't see it begin).
- spike:       a bucket ≥ SPIKE_RATIO × the trailing active average and
               ≥ SPIKE_MIN — emitted once, for the biggest such bucket.
- subsides:    activity stops ≥ QUIET_BUCKETS before the window end
               (total ≥ SUBSIDE_MIN so one stray line doesn't "subside").
- new_pattern: the signature's first-ever occurrence falls inside the
               window (replaces `begins` for that series).
- health:      per-service error fraction crosses DEGRADED_FRAC with at
               least HEALTH_MIN rows in the bucket → "enters degraded
               state"; falls back below RECOVERED_FRAC → "recovers".
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta
from typing import Optional
from uuid import UUID

import asyncpg

from repi.core.dates import DateHandler

logger = logging.getLogger(__name__)

ERROR_CLASS = {"ERROR", "CRITICAL", "FATAL", "WARN", "WARNING"}

N_BUCKETS = 24
BEGINS_MIN = 3
SPIKE_RATIO = 3.0
SPIKE_MIN = 5
QUIET_BUCKETS = 2
SUBSIDE_MIN = 5
DEGRADED_FRAC = 0.5
RECOVERED_FRAC = 0.25
HEALTH_MIN = 10

# Rank used when the event list exceeds max_events: keep the most significant,
# then re-sort chronologically so the story still reads in order.
KIND_PRIORITY = {
    "health_degraded": 0,
    "new_pattern": 1,
    "begins": 2,
    "spike": 3,
    "health_recovered": 4,
    "subsides": 5,
}


@dataclass
class TimelineEvent:
    kind: str
    ts: str  # ISO8601 — bucket boundary the event is anchored to
    service: Optional[str]
    signature: Optional[str]
    level: Optional[str]
    title: str
    count: int = 0

    def to_dict(self) -> dict:
        return asdict(self)


def parse_window(window: str) -> timedelta:
    """'5h' → timedelta(hours=5). Supports m/h/d suffixes; defaults to 5h on
    anything unparseable (the overview should degrade, not 500)."""
    try:
        unit = window.strip()[-1].lower()
        value = int(window.strip()[:-1])
        if value <= 0:
            raise ValueError
        return {"m": timedelta(minutes=value),
                "h": timedelta(hours=value),
                "d": timedelta(days=value)}[unit]
    except (ValueError, KeyError, IndexError):
        logger.warning("parse_window: unparseable window %r — defaulting to 5h", window)
        return timedelta(hours=5)


async def fetch_window_aggregates(
    pool: asyncpg.Pool,
    project_id: UUID,
    time_from: datetime,
    time_to: datetime,
    n_buckets: int = N_BUCKETS,
    service: Optional[str] = None,
) -> tuple[list[dict], dict[str, datetime]]:
    """Bucket counts per (service, signature, level) + first-ever timestamp
    per signature (for new_pattern detection)."""
    tf = DateHandler.to_aware_utc(time_from)
    tt = DateHandler.to_aware_utc(time_to)
    rows = await pool.fetch(
        """
        SELECT source_service AS service, signature, log_level AS level,
               width_bucket(extract(epoch FROM timestamp_start),
                            extract(epoch FROM $2::timestamptz),
                            extract(epoch FROM $3::timestamptz), $4) AS bucket,
               count(*) AS n
        FROM log_chunks
        WHERE project_id = $1
          AND timestamp_start >= $2 AND timestamp_start < $3
          AND signature IS NOT NULL AND signature <> ''
          AND ($5::text IS NULL OR source_service = $5)
        GROUP BY 1, 2, 3, 4
        """,
        project_id, tf, tt, n_buckets, service,
    )
    buckets = [dict(r) for r in rows]

    sigs = sorted({r["signature"] for r in buckets})
    first_seen: dict[str, datetime] = {}
    if sigs:
        fs_rows = await pool.fetch(
            """
            SELECT signature, MIN(timestamp_start) AS first_ever
            FROM log_chunks
            WHERE project_id = $1 AND signature = ANY($2)
            GROUP BY signature
            """,
            project_id, sigs,
        )
        first_seen = {r["signature"]: r["first_ever"] for r in fs_rows}
    return buckets, first_seen


def derive_events(
    buckets: list[dict],
    first_seen: dict[str, datetime],
    time_from: datetime,
    time_to: datetime,
    n_buckets: int = N_BUCKETS,
    max_events: int = 25,
) -> list[dict]:
    """Pure rule engine: bucket aggregates → chronological event dicts.

    `buckets` rows: {service, signature, level, bucket (1-based, from
    width_bucket), n}. `first_seen`: signature → first-ever timestamp.
    """
    tf = DateHandler.to_aware_utc(time_from)
    tt = DateHandler.to_aware_utc(time_to)
    bucket_span = (tt - tf) / n_buckets

    def bucket_start(b: int) -> str:
        return DateHandler.to_iso(tf + bucket_span * (b - 1))

    def bucket_end(b: int) -> str:
        return DateHandler.to_iso(tf + bucket_span * b)

    # ── series per (service, signature), error-class rows only ──────────────
    series: dict[tuple, dict] = {}
    # ── per-service totals per bucket for health events ──────────────────────
    svc_total: dict[str, dict[int, int]] = {}
    svc_err: dict[str, dict[int, int]] = {}

    for r in buckets:
        b = int(r["bucket"])
        if b < 1 or b > n_buckets:
            continue
        svc = r["service"]
        level = (r["level"] or "").upper()
        n = int(r["n"])
        svc_total.setdefault(svc, {})
        svc_total[svc][b] = svc_total[svc].get(b, 0) + n
        if level not in ERROR_CLASS:
            continue
        svc_err.setdefault(svc, {})
        svc_err[svc][b] = svc_err[svc].get(b, 0) + n
        key = (svc, r["signature"])
        s = series.setdefault(key, {"counts": {}, "level": level})
        s["counts"][b] = s["counts"].get(b, 0) + n
        # Keep the most severe level seen for display.
        rank = {"FATAL": 3, "CRITICAL": 3, "ERROR": 2, "WARNING": 1, "WARN": 1}
        if rank.get(level, 0) > rank.get(s["level"], 0):
            s["level"] = level

    events: list[TimelineEvent] = []

    for (svc, sig), s in series.items():
        counts = s["counts"]
        level = s["level"]
        active = sorted(counts.keys())
        first_b, last_b = active[0], active[-1]
        total = sum(counts.values())

        is_new = False
        fe = first_seen.get(sig)
        if fe is not None and DateHandler.to_aware_utc(fe) >= tf:
            is_new = True
            events.append(TimelineEvent(
                kind="new_pattern", ts=bucket_start(first_b), service=svc,
                signature=sig, level=level,
                title=f"New error pattern: {sig}", count=counts[first_b],
            ))

        if not is_new and first_b > 1 and counts[first_b] >= BEGINS_MIN:
            events.append(TimelineEvent(
                kind="begins", ts=bucket_start(first_b), service=svc,
                signature=sig, level=level,
                title=f"{sig} begins", count=counts[first_b],
            ))

        # Spike: biggest bucket vs trailing active average before it.
        best = None
        for b in active[1:]:
            prior = [counts[x] for x in active if x < b]
            trailing_avg = sum(prior) / len(prior)
            if counts[b] >= SPIKE_MIN and counts[b] >= SPIKE_RATIO * trailing_avg:
                if best is None or counts[b] > counts[best]:
                    best = b
        if best is not None:
            events.append(TimelineEvent(
                kind="spike", ts=bucket_start(best), service=svc,
                signature=sig, level=level,
                title=f"{sig} spikes (×{counts[best]})", count=counts[best],
            ))

        if total >= SUBSIDE_MIN and last_b <= n_buckets - QUIET_BUCKETS:
            events.append(TimelineEvent(
                kind="subsides", ts=bucket_end(last_b), service=svc,
                signature=sig, level=level,
                title=f"{sig} subsides", count=0,
            ))

    # ── health transitions per service ───────────────────────────────────────
    for svc, totals in svc_total.items():
        errs = svc_err.get(svc, {})
        degraded = False
        for b in range(1, n_buckets + 1):
            tot = totals.get(b, 0)
            if tot < HEALTH_MIN:
                continue
            frac = errs.get(b, 0) / tot
            if not degraded and frac >= DEGRADED_FRAC:
                degraded = True
                events.append(TimelineEvent(
                    kind="health_degraded", ts=bucket_start(b), service=svc,
                    signature=None, level="ERROR",
                    title=f"{svc} enters degraded state", count=errs.get(b, 0),
                ))
            elif degraded and frac <= RECOVERED_FRAC:
                degraded = False
                events.append(TimelineEvent(
                    kind="health_recovered", ts=bucket_start(b), service=svc,
                    signature=None, level="INFO",
                    title=f"{svc} recovers", count=0,
                ))

    if len(events) > max_events:
        events.sort(key=lambda e: (KIND_PRIORITY.get(e.kind, 9), -e.count))
        events = events[:max_events]
    events.sort(key=lambda e: e.ts)
    return [e.to_dict() for e in events]
