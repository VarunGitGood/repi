"""FastAPI dependencies enforcing the read-only demo lock (see Settings.DEMO_MODE).

`block_in_demo` 403s mutating / non-showcase endpoints. `llm_daily_budget` caps
the combined token-burning endpoints (investigate + clarify + chat) at a shared
per-UTC-day budget so a public demo can't drain provider credits.
"""
from __future__ import annotations

import datetime as _dt

from fastapi import HTTPException

from repi.core.config import settings


async def block_in_demo() -> None:
    """403 when the read-only demo lock is on."""
    if settings.DEMO_MODE:
        raise HTTPException(status_code=403, detail="Disabled in read-only demo mode.")


# Shared across every LLM endpoint so the cap is one wallet-wide bucket, not
# per-endpoint or per-IP. In-memory by design: with scale-to-zero the count
# resets on cold start, making the budget per-uptime-window. Back this with
# Redis if a hard cross-restart budget is ever required.
_budget = {"date": None, "count": 0}


async def llm_daily_budget() -> None:
    """Enforce the shared daily LLM call budget while DEMO_MODE is on."""
    if not settings.DEMO_MODE:
        return
    today = _dt.datetime.now(_dt.timezone.utc).date()
    if _budget["date"] != today:
        _budget["date"] = today
        _budget["count"] = 0
    if _budget["count"] >= settings.DEMO_DAILY_LLM_BUDGET:
        raise HTTPException(
            status_code=429,
            detail="Daily demo budget reached — please try again tomorrow.",
        )
    _budget["count"] += 1
