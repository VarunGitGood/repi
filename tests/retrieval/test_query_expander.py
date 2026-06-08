"""Cap + dedup contract for QueryExpander.

Static synonym dictionary and LLM expansion live elsewhere; here we verify
the post-merge guarantees the rest of the retrieval pipeline relies on:
total ≤ MAX_VARIANTS, original first, case-insensitive dedup.
"""
from __future__ import annotations

import pytest

from repi.retrieval import query_expander
from repi.retrieval.query_expander import MAX_VARIANTS, QueryExpander, expand_query_static


def test_static_expansion_returns_at_least_the_original():
    out = expand_query_static("payments timing out")
    assert out[0] == "payments timing out"


@pytest.mark.asyncio
async def test_expand_caps_total_variants():
    """Even with the rich 'database connection error' query (matches multiple
    synonym buckets) the post-cap list is no longer than MAX_VARIANTS."""
    exp = QueryExpander(llm=None)
    out = await exp.expand("database connection error timeout")
    assert 1 <= len(out) <= MAX_VARIANTS


@pytest.mark.asyncio
async def test_expand_case_insensitive_dedup(monkeypatch):
    """A variant that only differs in case from another must be dropped."""
    # Static expansion produces variants by lowercasing first → already
    # mostly normalised. Inject case-divergent variants via the LLM hook to
    # exercise the dedup pass.
    async def fake_llm_expand(self, query):
        return ["PAYMENT ERROR", "payment error", "Payment   Error"]

    monkeypatch.setattr(QueryExpander, "_llm_expand", fake_llm_expand)

    class _StubLLM:  # presence triggers the LLM branch
        pass

    exp = QueryExpander(llm=_StubLLM())
    out = await exp.expand("payment error")

    # Case-insensitive equivalent variants collapse to one.
    lowered = [v.strip().lower() for v in out]
    assert len(set(lowered)) == len(lowered)


@pytest.mark.asyncio
async def test_expand_keeps_original_first():
    exp = QueryExpander(llm=None)
    out = await exp.expand("connection refused")
    assert out[0] == "connection refused"


@pytest.mark.asyncio
async def test_expand_llm_failure_does_not_break_static(monkeypatch):
    async def boom(self, query):
        raise RuntimeError("provider down")

    monkeypatch.setattr(QueryExpander, "_llm_expand", boom)

    class _StubLLM:
        pass

    exp = QueryExpander(llm=_StubLLM())
    out = await exp.expand("redis timeout")
    assert out  # static fallback still produced something
    assert out[0] == "redis timeout"
