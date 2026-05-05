"""
Central date-handling for repi.

All datetimes inside the system are naive UTC.  The boundary conversions are:

  input (ISO string / user local) ─► to_utc_naive()  ─► internal naive UTC
  internal naive UTC              ─► to_iso()         ─► ISO 8601 string output
  display back to user            ─► to_user_tz()      ─► user-local aware datetime

Never instantiate datetimes with .utcnow() elsewhere; use DateHandler.now() so
the clock source is replaceable in tests.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

logger = logging.getLogger(__name__)

_UTC = timezone.utc


class DateHandler:
    """Singleton-style helper; instantiate once with a timezone, pass it around."""

    def __init__(self, user_tz: str = "UTC") -> None:
        self.user_tz: ZoneInfo = self._load_tz(user_tz)

    # ── Construction ──────────────────────────────────────────────────────────

    @staticmethod
    def _load_tz(tz_str: str) -> ZoneInfo:
        try:
            return ZoneInfo(tz_str)
        except (ZoneInfoNotFoundError, Exception):
            logger.warning("Unknown timezone %r — falling back to UTC", tz_str)
            return ZoneInfo("UTC")

    # ── Clock ─────────────────────────────────────────────────────────────────

    def now(self) -> datetime:
        """Return current time as naive UTC. Use this instead of datetime.utcnow()."""
        return datetime.now(_UTC).replace(tzinfo=None)

    def now_local(self) -> datetime:
        """Return current time as aware datetime in the user's timezone."""
        return datetime.now(_UTC).astimezone(self.user_tz)

    # ── Conversion: any input → naive UTC ────────────────────────────────────

    @staticmethod
    def to_utc_naive(dt: datetime | None) -> datetime | None:
        """Convert any datetime to naive UTC. Returns None if input is None."""
        if dt is None:
            return None
        if dt.tzinfo is None:
            return dt
        return dt.astimezone(_UTC).replace(tzinfo=None)

    @staticmethod
    def parse_iso(ts: str | None) -> datetime | None:
        """
        Parse an ISO 8601 string (with or without Z / offset) into naive UTC.
        Returns None on empty input; logs a warning on parse failure.
        """
        if not ts:
            return None
        try:
            dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            return DateHandler.to_utc_naive(dt)
        except ValueError:
            logger.warning("Failed to parse ISO timestamp: %r", ts)
            return None

    def local_to_utc(self, dt: datetime) -> datetime:
        """
        Attach the user timezone to a naive datetime, then convert to naive UTC.
        Use this when the input is known to be in the user's local time.
        """
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=self.user_tz)
        return self.to_utc_naive(dt)

    # ── Conversion: naive UTC → output ───────────────────────────────────────

    @staticmethod
    def to_iso(dt: datetime | None) -> str | None:
        """Format a naive-UTC datetime as an ISO 8601 string (no trailing +00:00)."""
        if dt is None:
            return None
        return dt.isoformat()

    def to_user_tz(self, dt: datetime) -> datetime:
        """Convert a naive-UTC datetime to an aware datetime in the user's timezone."""
        return dt.replace(tzinfo=_UTC).astimezone(self.user_tz)

    # ── Helpers ───────────────────────────────────────────────────────────────

    def ago(self, **kwargs) -> datetime:
        """Return naive UTC datetime N units ago. kwargs forwarded to timedelta."""
        return self.now() - timedelta(**kwargs)

    def window(self, **kwargs) -> tuple[datetime, datetime]:
        """Return (now - delta, now) as naive UTC datetimes."""
        return self.ago(**kwargs), self.now()


# Module-level default instance (UTC).  Callers that need a user timezone
# should construct their own DateHandler(user_tz="...").
default_date_handler = DateHandler()
