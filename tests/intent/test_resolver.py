from datetime import datetime

from repi.intent.resolver import (
    ClarificationNeeded,
    ResolvedIntent,
    _extract_entities,
    resolve,
)


# Fixed "now" — a Wednesday so weekday parsing is deterministic.
NOW = datetime(2026, 6, 10, 12, 0, 0)


# ── Gate behaviour ────────────────────────────────────────────────────────────

def test_entity_only_no_clarification():
    """A Stripe-style prefixed ID with no time and no service must not clarify."""
    res = resolve(
        "why did ch_3MX8K2eZvKYlo2C1aBcDeFg fail",
        known_services=[],
        now=NOW,
    )
    assert isinstance(res, ResolvedIntent)
    assert "ch_3MX8K2eZvKYlo2C1aBcDeFg" in res.entities
    assert res.time_from is None
    assert res.time_to is None
    assert res.services == []


def test_service_only_no_clarification():
    """A known service with no time must NOT clarify and must NOT default to 1h."""
    res = resolve("errors in cart-svc", known_services=["cart-svc"], now=NOW)
    assert isinstance(res, ResolvedIntent)
    assert res.services == ["cart-svc"]
    assert res.time_from is None
    assert res.time_to is None


def test_time_only_no_clarification():
    res = resolve("last 2 hours", known_services=["cart-svc"], now=NOW)
    assert isinstance(res, ResolvedIntent)
    assert res.time_from is not None
    assert res.time_to is not None
    assert res.services == []
    assert res.entities == []


def test_all_three_missing_clarifies():
    """No id, no service, no time → single unified clarification."""
    res = resolve("why did things break", known_services=["cart-svc"], now=NOW)
    assert isinstance(res, ClarificationNeeded)
    assert res.missing_dims == ["id_or_service_or_time"]
    # Clarification message must not leak dataset-specific jargon.
    assert "blk_" not in res.question.lower()
    assert "identifier" in res.question.lower()
    assert "service" in res.question.lower()
    assert "time" in res.question.lower()


def test_symptom_alone_does_not_satisfy_gate():
    """Per A3 spec: symptoms (errors/timeouts) do NOT count as a dimension."""
    res = resolve("seeing 500 errors", known_services=["cart-svc"], now=NOW)
    assert isinstance(res, ClarificationNeeded)


def test_no_default_to_last_hour():
    """The old 'default to last 1 hour' fallback is gone."""
    res = resolve("ch_3MX8K2eZvKYlo2C1aBcDeFg", known_services=[], now=NOW)
    assert isinstance(res, ResolvedIntent)
    assert res.time_from is None
    assert res.time_to is None
    assert not any("defaulting" in a for a in res.assumed)


def test_ambiguous_weekday_rescued_by_entity():
    """User says weekday matching today without 'last/this' — time stays None,
    but the entity rescues the gate so we proceed without clarification."""
    res = resolve("ch_3MX8K2eZvKYlo2C1aBcDeFg failed wednesday", known_services=[], now=NOW)
    assert isinstance(res, ResolvedIntent)
    assert "ch_3MX8K2eZvKYlo2C1aBcDeFg" in res.entities
    assert res.time_from is None


# ── Entity extraction — industry-standard IDs ─────────────────────────────────

def test_extract_uuid():
    out = _extract_entities("trace 550e8400-e29b-41d4-a716-446655440000", [])
    assert out == ["550e8400-e29b-41d4-a716-446655440000"]


def test_extract_w3c_trace_id():
    """W3C TraceContext trace-id: exactly 32 lowercase hex chars."""
    out = _extract_entities("trace 4bf92f3577b34da6a3ce929d0e0e4736 failed", [])
    assert out == ["4bf92f3577b34da6a3ce929d0e0e4736"]


def test_extract_w3c_span_id():
    """W3C TraceContext span-id: exactly 16 lowercase hex chars."""
    out = _extract_entities("span 00f067aa0ba902b7 was slow", [])
    assert out == ["00f067aa0ba902b7"]


def test_extract_ulid():
    """Crockford base32 — 26 chars, no I/L/O/U."""
    out = _extract_entities("see ULID 01ARZ3NDEKTSV4RRFFQ69G5FAV", [])
    assert "01ARZ3NDEKTSV4RRFFQ69G5FAV" in out


def test_extract_stripe_style_prefixed_id():
    """Stripe/Twilio/Auth0-style `prefix_body` IDs."""
    out = _extract_entities("charge ch_3MX8K2eZvKYlo2C1aBcDeFg", [])
    assert "ch_3MX8K2eZvKYlo2C1aBcDeFg" in out


def test_extract_aws_resource_id():
    out = _extract_entities("instance i-0abc123def4567890 down", [])
    assert "i-0abc123def4567890" in out


def test_extract_aws_arn():
    out = _extract_entities(
        "arn:aws:iam::123456789012:role/MyRole denied",
        [],
    )
    assert any(e.startswith("arn:aws:") for e in out)


def test_extract_git_sha_excludes_pure_digit_strings():
    """Commit SHA pattern must NOT capture epoch timestamps (all-digit hex)."""
    # 1717000000 is a valid epoch but has no [a-f] — must NOT be tagged as a SHA.
    out = _extract_entities("error at 1717000000 in commit a1b2c3def", [])
    assert "1717000000" not in out
    assert "a1b2c3def" in out


def test_hyphenated_compound_without_digit_not_extracted():
    """English compounds like 'post-mortem' must NOT be tagged as entities."""
    out = _extract_entities("post-mortem on the self-service flow", [])
    assert out == []


def test_hyphenated_id_with_digit_extracted():
    """Hyphenated IDs containing a digit are real (order-12345, k8s pods, …)."""
    out = _extract_entities("order order-12345 stuck on pod nginx-7d4b8c-xyz12", [])
    assert "order-12345" in out
    assert "nginx-7d4b8c-xyz12" in out


def test_known_service_not_extracted_as_entity():
    """A known service like 'cart-svc-2' must not double-count as an entity even
    though it matches the hyphenated-identifier pattern (it has a digit)."""
    out = _extract_entities("errors in cart-svc-2", ["cart-svc-2"])
    assert out == []


def test_entity_dedup_case_insensitive():
    out = _extract_entities(
        "trace 4BF92F3577B34DA6A3CE929D0E0E4736 then 4bf92f3577b34da6a3ce929d0e0e4736",
        [],
    )
    assert len(out) == 1


# ── Extensibility: user-supplied ENTITY_REGEX_EXTRA ───────────────────────────

def test_user_supplied_pattern_via_extra_patterns():
    """An HDFS-shop user adds `blk_-?\\d+` via Settings.ENTITY_REGEX_EXTRA;
    the resolver picks it up without code changes."""
    out = _extract_entities(
        "why did blk_-1608999687919862906 fail",
        [],
        extra_patterns=[r"\bblk_-?\d+\b"],
    )
    assert "blk_-1608999687919862906" in out


def test_user_supplied_invalid_pattern_is_skipped():
    """An invalid regex must not crash the resolver; it's warned and skipped."""
    out = _extract_entities(
        "trace 550e8400-e29b-41d4-a716-446655440000",
        [],
        extra_patterns=["[invalid("],
    )
    # Default UUID pattern still works.
    assert out == ["550e8400-e29b-41d4-a716-446655440000"]
