"""Pin the chat path's timestamp invariant.

Downstream cluster_view and timeline_view do string comparisons (`<`, `>`,
`sorted(...)`) on `chunks[i]["timestamp"]`. If one chunk in that list
carries a `datetime` and another a `str`, the comparison TypeErrors at
runtime — which is exactly the failure mode the PR #71 review flagged.

`repi/api/chat.py::_normalize_ts` is the single point both feed paths
(RRF retrieval, entity-bias merge from find_logs_by_id) run through.
This test pins its contract so a future change can't reintroduce mixed
shapes.
"""
from __future__ import annotations

from datetime import datetime, timezone

from repi.api.chat import _normalize_ts


def test_normalize_ts_none_passthrough():
    assert _normalize_ts(None) is None


def test_normalize_ts_aware_datetime_becomes_iso_string():
    out = _normalize_ts(datetime(2026, 6, 9, 14, 2, 0, tzinfo=timezone.utc))
    assert isinstance(out, str)
    assert out.startswith("2026-06-09T14:02:00")


def test_normalize_ts_naive_datetime_becomes_iso_string():
    out = _normalize_ts(datetime(2026, 6, 9, 14, 2, 0))
    assert isinstance(out, str)
    assert out.startswith("2026-06-09T14:02:00")


def test_normalize_ts_existing_string_passthrough():
    """find_logs_by_id already ISO-stringifies upstream; passing its output
    through the helper is idempotent."""
    assert _normalize_ts("2026-06-09T14:02:00") == "2026-06-09T14:02:00"
