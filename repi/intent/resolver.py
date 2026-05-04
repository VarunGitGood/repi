from __future__ import annotations
import re
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, time as dtime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

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
    assumed: list[str] = field(default_factory=list)


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


def _tz(timezone_str: str) -> ZoneInfo:
    try:
        return ZoneInfo(timezone_str)
    except (ZoneInfoNotFoundError, Exception):
        logger.warning(f"Unknown timezone {timezone_str!r}, falling back to UTC")
        return ZoneInfo("UTC")


def _to_utc(dt: datetime, tz: ZoneInfo) -> datetime:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=tz)
    return dt.astimezone(ZoneInfo("UTC")).replace(tzinfo=None)


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
    tz = _tz(timezone_str)
    now_local = now.replace(tzinfo=ZoneInfo("UTC")).astimezone(tz) if now.tzinfo is None else now.astimezone(tz)
    q = query.lower()

    time_from: datetime | None = None
    time_to: datetime | None = None
    assumed: list[str] = []
    missing_dims: list[str] = []

    # ── Time parsing ──────────────────────────────────────────────────────────

    # last N minutes
    m = re.search(r"last\s+(\d+)\s+(?:minutes?|mins?)", q)
    if m:
        time_from = _to_utc(now_local - timedelta(minutes=int(m.group(1))), tz)
        time_to = _to_utc(now_local, tz)

    # last N hours
    if time_from is None:
        m = re.search(r"last\s+(\d+)\s+(?:hours?|h\b)", q)
        if m:
            time_from = _to_utc(now_local - timedelta(hours=int(m.group(1))), tz)
            time_to = _to_utc(now_local, tz)

    # last N days
    if time_from is None:
        m = re.search(r"last\s+(\d+)\s+days?", q)
        if m:
            time_from = _to_utc(now_local - timedelta(days=int(m.group(1))), tz)
            time_to = _to_utc(now_local, tz)

    # today
    if time_from is None and re.search(r"\btoday\b", q):
        midnight = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
        time_from = _to_utc(midnight, tz)
        time_to = _to_utc(now_local, tz)

    # yesterday
    if time_from is None and re.search(r"\byesterday\b", q):
        yesterday = (now_local - timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        time_from = _to_utc(yesterday, tz)
        time_to = _to_utc(yesterday.replace(hour=23, minute=59, second=59), tz)

    # this weekend
    if time_from is None and re.search(r"\bthis\s+weekend\b", q):
        saturday_dow = 5
        sat = _most_recent_weekday(saturday_dow, now_local)
        time_from = _to_utc(sat, tz)
        time_to = _to_utc(sat.replace(hour=23, minute=59, second=59) + timedelta(days=1), tz)

    # since HH:MM
    if time_from is None:
        m = re.search(r"\bsince\s+(\d{1,2}):(\d{2})\b", q)
        if m:
            hh, mm = int(m.group(1)), int(m.group(2))
            candidate = now_local.replace(hour=hh, minute=mm, second=0, microsecond=0)
            if candidate > now_local:
                candidate -= timedelta(days=1)
            time_from = _to_utc(candidate, tz)
            time_to = _to_utc(now_local, tz)

    # last night
    if time_from is None and re.search(r"\blast\s+night\b", q):
        yesterday = now_local - timedelta(days=1)
        night_start = yesterday.replace(hour=22, minute=0, second=0, microsecond=0)
        night_end = now_local.replace(hour=6, minute=0, second=0, microsecond=0)
        if night_end < now_local:
            pass  # still before 06:00 today — window is fine
        time_from = _to_utc(night_start, tz)
        time_to = _to_utc(night_end, tz)
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
            time_from = _to_utc(centre - timedelta(minutes=15), tz)
            time_to = _to_utc(centre + timedelta(minutes=15), tz)

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
            time_from = _to_utc(start, tz)
            time_to = _to_utc(end, tz)

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
            ambiguous_weekday = not m_wd.group(1)  # no "last"/"this" prefix
            dow = WEEKDAY_MAP[m_wd.group(2)]
            pod = m_wd.group(3)

            day_midnight = _most_recent_weekday(dow, now_local, force_last_week=force_last)

            # Ambiguity: no prefix and today is the same weekday
            if ambiguous_weekday and now_local.weekday() == dow:
                missing_dims.append("time")
            else:
                if pod:
                    start_h, end_h = PARTS_OF_DAY[pod]
                    start = day_midnight.replace(hour=start_h, minute=0, second=0)
                    if end_h > 24:  # night wraps to next day
                        end = (day_midnight + timedelta(days=1)).replace(hour=end_h - 24, minute=0, second=0)
                    else:
                        end = day_midnight.replace(hour=end_h, minute=0, second=0)
                    time_from = _to_utc(start, tz)
                    time_to = _to_utc(end, tz)
                    assumed.append(
                        f"'{m_wd.group(2)} {pod}' interpreted as {time_from.strftime('%Y-%m-%d %H:%M')} – "
                        f"{time_to.strftime('%Y-%m-%d %H:%M')} UTC"
                    )
                else:
                    time_from = _to_utc(day_midnight, tz)
                    time_to = _to_utc(day_midnight.replace(hour=23, minute=59, second=59), tz)
                    assumed.append(
                        f"'{m_wd.group(2)}' interpreted as {time_from.strftime('%Y-%m-%d')} UTC"
                    )

                # Optional: refine with "around HH:MM" or "around Xam/pm" on the same date
                m_around_hm = re.search(r"\baround\s+(\d{1,2}):(\d{2})\b", q)
                m_around_ap = re.search(r"\baround\s+(\d{1,2})\s*(am|pm)\b", q)
                if m_around_hm:
                    hh, mm = int(m_around_hm.group(1)), int(m_around_hm.group(2))
                    centre = day_midnight.replace(hour=hh, minute=mm, second=0)
                    time_from = _to_utc(centre - timedelta(minutes=30), tz)
                    time_to = _to_utc(centre + timedelta(minutes=30), tz)
                elif m_around_ap:
                    hh = int(m_around_ap.group(1))
                    if m_around_ap.group(2) == "pm" and hh != 12:
                        hh += 12
                    elif m_around_ap.group(2) == "am" and hh == 12:
                        hh = 0
                    centre = day_midnight.replace(hour=hh, minute=0, second=0)
                    time_from = _to_utc(centre - timedelta(minutes=30), tz)
                    time_to = _to_utc(centre + timedelta(minutes=30), tz)

    # around Xam / Xpm standalone (e.g. "around 3am") — only if no weekday already set a window
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
            time_from = _to_utc(centre - timedelta(minutes=30), tz)
            time_to = _to_utc(centre + timedelta(minutes=30), tz)

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

    # Check for unrecognized service-like words
    svc_like = re.findall(r"\b\w+(?:-\w+)+\b|\b\w+svc\b|\b\w+service\b|\b\w+api\b", q)
    for word in svc_like:
        if not any(_levenshtein(word, s.lower()) <= 2 for s in known_services):
            if "service" not in missing_dims:
                missing_dims.append("service")

    if not found_services:
        assumed.append("no service named in query — searching all known services")

    # ── Symptom extraction ────────────────────────────────────────────────────
    found_symptoms = [kw for kw in SYMPTOM_VOCAB if kw in q]

    # ── Ambiguity check ───────────────────────────────────────────────────────
    if time_from is None and "time" not in missing_dims:
        if not found_symptoms:
            missing_dims.append("time")

    if missing_dims:
        question = _build_question(missing_dims, known_services)
        return ClarificationNeeded(question=question, missing_dims=missing_dims)

    # If time_from is still None but we have symptoms, use a sensible default window
    if time_from is None:
        time_from = _to_utc(now_local - timedelta(hours=1), tz)
        time_to = _to_utc(now_local, tz)
        assumed.append("no time specified — defaulting to last 1 hour")

    if time_to is None:
        time_to = _to_utc(now_local, tz)

    return ResolvedIntent(
        time_from=time_from,
        time_to=time_to,
        services=found_services,
        symptoms=found_symptoms,
        assumed=assumed,
    )


def _build_question(missing_dims: list[str], known_services: list[str]) -> str:
    parts: list[str] = []
    if "time" in missing_dims:
        parts.append(
            "when did this happen? "
            "(e.g. 'last Friday evening around 10pm', 'yesterday morning', 'last 2 hours')"
        )
    if "service" in missing_dims and known_services:
        svc_list = ", ".join(known_services)
        parts.append(f"which service are you asking about? Known services: {svc_list}")

    if len(parts) == 1:
        return "Could you clarify: " + parts[0]
    items = "\n".join(f"- {p}" for p in parts)
    return f"A couple of quick questions before I start:\n{items}"
