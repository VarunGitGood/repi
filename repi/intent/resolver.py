from __future__ import annotations
import re
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from repi.core.dates import DateHandler

logger = logging.getLogger(__name__)

SYMPTOM_VOCAB = {
    "5xx", "500", "timeout", "latency", "slow", "oom", "crash",
    "restart", "down", "unreachable", "connection refused", "pool exhausted",
    "auth", "denied", "forbidden", "failed", "exception", "error",
}

WEEKDAY_MAP = {
    "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
    "friday": 4, "saturday": 5, "sunday": 6,
    "mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6,
}

PARTS_OF_DAY = {
    "morning":   (6, 12),
    "afternoon": (12, 18),
    "evening":   (18, 22),
    "night":     (22, 30),  # 30 means next-day 06:00
}


@dataclass
class ResolvedIntent:
    time_from: datetime | None
    time_to: datetime | None
    services: list[str] = field(default_factory=list)
    symptoms: list[str] = field(default_factory=list)
    entities: list[str] = field(default_factory=list)
    assumed: list[str] = field(default_factory=list)


# Entity regex layer. Order matters: longer/more-specific patterns first so
# (e.g.) a UUID match isn't shadowed by the generic hex-hash one.
ENTITY_PATTERNS = [
    re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", re.IGNORECASE),
    re.compile(r"\bblk_-?\d+\b", re.IGNORECASE),
    re.compile(r"\breq_[\w-]+\b", re.IGNORECASE),
    re.compile(r"\b[0-9a-f]{8,}\b", re.IGNORECASE),
    re.compile(r"\b[A-Za-z][\w]*(?:-[\w.]+){1,}\b"),
]


def _extract_entities(query: str, known_services: list[str]) -> list[str]:
    """Pull ID-like tokens from the raw (case-preserved) query.

    Patterns run in priority order (longer/more-specific first). Spans claimed
    by an earlier pattern are not re-matched by later ones, so the trailing
    digits of `blk_-1608…` aren't re-emitted as a hex hash and the segments of
    a UUID aren't re-emitted as separate hex tokens.

    Matches are deduped (case-insensitive) and stripped against `known_services`
    so a known service name like 'cart-svc' isn't double-counted as an entity.
    """
    known_lower = {s.lower() for s in known_services}
    seen: set[str] = set()
    claimed: list[tuple[int, int]] = []
    out: list[str] = []
    for pat in ENTITY_PATTERNS:
        for m in pat.finditer(query):
            start, end = m.span()
            if any(s < end and start < e for s, e in claimed):
                continue
            token = m.group(0)
            key = token.lower()
            if key in seen or key in known_lower:
                claimed.append((start, end))
                continue
            seen.add(key)
            claimed.append((start, end))
            out.append(token)
    return out


@dataclass
class ClarificationNeeded:
    question: str
    missing_dims: list[str] = field(default_factory=list)


def _levenshtein(a: str, b: str) -> int:
    if len(a) < len(b):
        a, b = b, a
    row = list(range(len(b) + 1))
    for i, ca in enumerate(a):
        new_row = [i + 1]
        for j, cb in enumerate(b):
            new_row.append(min(row[j + 1] + 1, new_row[j] + 1, row[j] + (ca != cb)))
        row = new_row
    return row[-1]


def _most_recent_weekday(target_dow: int, now_local: datetime, force_last_week: bool = False) -> datetime:
    """Return midnight (local) of the most recent occurrence of target_dow."""
    days_back = (now_local.weekday() - target_dow) % 7
    if days_back == 0:
        days_back = 7 if force_last_week else 0
    return (now_local - timedelta(days=days_back)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )


def resolve(
    query: str,
    known_services: list[str],
    now: datetime,
    timezone_str: str = "UTC",
) -> ResolvedIntent | ClarificationNeeded:
    dh = DateHandler(timezone_str)
    # now is always passed in as naive UTC from the caller
    now_local = dh.to_user_tz(now) if now.tzinfo is None else now.astimezone(dh.user_tz)
    q = query.lower()

    time_from: datetime | None = None
    time_to: datetime | None = None
    assumed: list[str] = []

    # ── Time parsing ──────────────────────────────────────────────────────────

    # last N minutes
    m = re.search(r"last\s+(\d+)\s+(?:minutes?|mins?)", q)
    if m:
        time_from = dh.local_to_utc(now_local - timedelta(minutes=int(m.group(1))))
        time_to = dh.local_to_utc(now_local)

    # last N hours
    if time_from is None:
        m = re.search(r"last\s+(\d+)\s+(?:hours?|h\b)", q)
        if m:
            time_from = dh.local_to_utc(now_local - timedelta(hours=int(m.group(1))))
            time_to = dh.local_to_utc(now_local)

    # last N days
    if time_from is None:
        m = re.search(r"last\s+(\d+)\s+days?", q)
        if m:
            time_from = dh.local_to_utc(now_local - timedelta(days=int(m.group(1))))
            time_to = dh.local_to_utc(now_local)

    # today
    if time_from is None and re.search(r"\btoday\b", q):
        midnight = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
        time_from = dh.local_to_utc(midnight)
        time_to = dh.local_to_utc(now_local)

    # yesterday
    if time_from is None and re.search(r"\byesterday\b", q):
        yesterday = (now_local - timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        time_from = dh.local_to_utc(yesterday)
        time_to = dh.local_to_utc(yesterday.replace(hour=23, minute=59, second=59))

    # this weekend
    if time_from is None and re.search(r"\bthis\s+weekend\b", q):
        sat = _most_recent_weekday(5, now_local)
        time_from = dh.local_to_utc(sat)
        time_to = dh.local_to_utc(sat.replace(hour=23, minute=59, second=59) + timedelta(days=1))

    # since HH:MM
    if time_from is None:
        m = re.search(r"\bsince\s+(\d{1,2}):(\d{2})\b", q)
        if m:
            hh, mm = int(m.group(1)), int(m.group(2))
            candidate = now_local.replace(hour=hh, minute=mm, second=0, microsecond=0)
            if candidate > now_local:
                candidate -= timedelta(days=1)
            time_from = dh.local_to_utc(candidate)
            time_to = dh.local_to_utc(now_local)

    # this morning / this afternoon / this evening / tonight
    # Resolves to today's window for that part-of-day (capped at now).
    if time_from is None:
        today_phrases = [
            ("this morning",   (6, 12)),
            ("this afternoon", (12, 18)),
            ("this evening",   (18, 22)),
            ("tonight",        (22, 30)),  # 30 means next-day 06:00
        ]
        for phrase, (start_h, end_h) in today_phrases:
            if re.search(rf"\b{re.escape(phrase)}\b", q):
                today_midnight = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
                start = today_midnight.replace(hour=start_h)
                if end_h > 24:
                    end = (today_midnight + timedelta(days=1)).replace(hour=end_h - 24)
                else:
                    end = today_midnight.replace(hour=end_h)
                end = min(end, now_local)  # cap at now if we're inside the window
                time_from = dh.local_to_utc(start)
                time_to = dh.local_to_utc(end)
                assumed.append(
                    f"'{phrase}' interpreted as {time_from.strftime('%Y-%m-%d %H:%M')} – "
                    f"{time_to.strftime('%Y-%m-%d %H:%M')} UTC"
                )
                break

    # last night
    if time_from is None and re.search(r"\blast\s+night\b", q):
        yesterday = now_local - timedelta(days=1)
        night_start = yesterday.replace(hour=22, minute=0, second=0, microsecond=0)
        night_end = now_local.replace(hour=6, minute=0, second=0, microsecond=0)
        time_from = dh.local_to_utc(night_start)
        time_to = dh.local_to_utc(night_end)
        assumed.append(
            f"'last night' interpreted as {time_from.strftime('%Y-%m-%d %H:%M')} – "
            f"{time_to.strftime('%Y-%m-%d %H:%M')} UTC"
        )

    # around HH:MM  (standalone — weekday compound is handled inside the weekday block below)
    if time_from is None:
        m = re.search(r"\baround\s+(\d{1,2}):(\d{2})\b", q)
        if m and not re.search("|".join(WEEKDAY_MAP.keys()), q):
            hh, mm = int(m.group(1)), int(m.group(2))
            centre = now_local.replace(hour=hh, minute=mm, second=0, microsecond=0)
            if centre > now_local:
                centre -= timedelta(days=1)
            time_from = dh.local_to_utc(centre - timedelta(minutes=15))
            time_to = dh.local_to_utc(centre + timedelta(minutes=15))

    # between HH:MM and HH:MM
    if time_from is None:
        m = re.search(r"\bbetween\s+(\d{1,2}):(\d{2})\s+and\s+(\d{1,2}):(\d{2})\b", q)
        if m:
            h1, m1, h2, m2 = int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4))
            start = now_local.replace(hour=h1, minute=m1, second=0, microsecond=0)
            end = now_local.replace(hour=h2, minute=m2, second=0, microsecond=0)
            if start > now_local:
                start -= timedelta(days=1)
                end -= timedelta(days=1)
            time_from = dh.local_to_utc(start)
            time_to = dh.local_to_utc(end)

    # weekday [+ part-of-day] [+ around H/HH:MM or around Xam/pm]
    # e.g. "last friday night", "wednesday around 3am", "last thursday around 03:00"
    if time_from is None:
        weekday_pat = "|".join(WEEKDAY_MAP.keys())
        pod_pat = "|".join(PARTS_OF_DAY.keys())
        m_wd = re.search(
            rf"\b(last\s+|this\s+)?({weekday_pat})\s*({pod_pat})?\b", q
        )
        if m_wd:
            force_last = bool(m_wd.group(1) and "last" in m_wd.group(1))
            ambiguous_weekday = not m_wd.group(1)
            dow = WEEKDAY_MAP[m_wd.group(2)]
            pod = m_wd.group(3)

            day_midnight = _most_recent_weekday(dow, now_local, force_last_week=force_last)

            if ambiguous_weekday and now_local.weekday() == dow:
                # "thursday" said on a Thursday with no "last"/"this" — genuinely
                # ambiguous which Thursday. Leave time unset; the gate decides
                # whether to clarify based on whether other dims rescue us.
                pass
            else:
                if pod:
                    start_h, end_h = PARTS_OF_DAY[pod]
                    start = day_midnight.replace(hour=start_h, minute=0, second=0)
                    if end_h > 24:  # night wraps to next day
                        end = (day_midnight + timedelta(days=1)).replace(hour=end_h - 24, minute=0, second=0)
                    else:
                        end = day_midnight.replace(hour=end_h, minute=0, second=0)
                    time_from = dh.local_to_utc(start)
                    time_to = dh.local_to_utc(end)
                    assumed.append(
                        f"'{m_wd.group(2)} {pod}' interpreted as {time_from.strftime('%Y-%m-%d %H:%M')} – "
                        f"{time_to.strftime('%Y-%m-%d %H:%M')} UTC"
                    )
                else:
                    time_from = dh.local_to_utc(day_midnight)
                    time_to = dh.local_to_utc(day_midnight.replace(hour=23, minute=59, second=59))
                    assumed.append(
                        f"'{m_wd.group(2)}' interpreted as {time_from.strftime('%Y-%m-%d')} UTC"
                    )

                # Refine with "around HH:MM" or "around Xam/pm" on the same date
                m_around_hm = re.search(r"\baround\s+(\d{1,2}):(\d{2})\b", q)
                m_around_ap = re.search(r"\baround\s+(\d{1,2})\s*(am|pm)\b", q)
                if m_around_hm:
                    hh, mm = int(m_around_hm.group(1)), int(m_around_hm.group(2))
                    centre = day_midnight.replace(hour=hh, minute=mm, second=0)
                    time_from = dh.local_to_utc(centre - timedelta(minutes=30))
                    time_to = dh.local_to_utc(centre + timedelta(minutes=30))
                elif m_around_ap:
                    hh = int(m_around_ap.group(1))
                    if m_around_ap.group(2) == "pm" and hh != 12:
                        hh += 12
                    elif m_around_ap.group(2) == "am" and hh == 12:
                        hh = 0
                    centre = day_midnight.replace(hour=hh, minute=0, second=0)
                    time_from = dh.local_to_utc(centre - timedelta(minutes=30))
                    time_to = dh.local_to_utc(centre + timedelta(minutes=30))

    # around Xam / Xpm standalone — only if no weekday already set a window
    if time_from is None:
        m = re.search(r"\baround\s+(\d{1,2})\s*(am|pm)\b", q)
        if m:
            hh = int(m.group(1))
            if m.group(2) == "pm" and hh != 12:
                hh += 12
            elif m.group(2) == "am" and hh == 12:
                hh = 0
            centre = now_local.replace(hour=hh, minute=0, second=0, microsecond=0)
            if centre > now_local:
                centre -= timedelta(days=1)
            time_from = dh.local_to_utc(centre - timedelta(minutes=30))
            time_to = dh.local_to_utc(centre + timedelta(minutes=30))

    # ── Service matching ──────────────────────────────────────────────────────
    found_services: list[str] = []
    for svc in known_services:
        if svc.lower() in q:
            found_services.append(svc)
            continue
        for word in re.findall(r"\b\w[\w-]*\b", q):
            if _levenshtein(word, svc.lower()) <= 2 and word not in {"why", "did", "the", "was", "are", "how"}:
                if svc not in found_services:
                    found_services.append(svc)
                break

    if not found_services:
        assumed.append("no service named in query — searching all known services")

    # ── Symptom extraction ────────────────────────────────────────────────────
    found_symptoms = [kw for kw in SYMPTOM_VOCAB if kw in q]

    # ── Entity extraction ─────────────────────────────────────────────────────
    # Run against the *original* (case-preserved) query so hex/UUID matching
    # is faithful. The function lower-cases internally for dedup.
    found_entities = _extract_entities(query, known_services)

    # ── Ambiguity check ───────────────────────────────────────────────────────
    # New contract: clarify ONLY when all three of {id, service, time} are
    # missing. Symptoms (5xx, timeout, etc.) do not satisfy the gate.
    # The internal "ambiguous_weekday" branch above may still flag time as
    # missing — honour that only if no entity/service rescues us.
    if time_from is None and not found_services and not found_entities:
        return ClarificationNeeded(
            question=(
                "I need at least one of: an ID (e.g. blk_42, req_abc), a service name, "
                "or a time window (e.g. 'last 2 hours'). Which do you have?"
            ),
            missing_dims=["id_or_service_or_time"],
        )

    # Time may legitimately remain None. Downstream (react_loop + tools) handles
    # the unbounded-window case explicitly — no silent default-to-last-1-hour.

    if time_from is not None and time_to is None:
        time_to = dh.local_to_utc(now_local)

    return ResolvedIntent(
        time_from=time_from,
        time_to=time_to,
        services=found_services,
        symptoms=found_symptoms,
        entities=found_entities,
        assumed=assumed,
    )


