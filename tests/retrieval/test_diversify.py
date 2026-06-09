"""Pure-function tests for the service-stratified diversification helper.

The function is the post-RRF reshuffle that keeps one noisy service from
dominating the top-K. We test the contract — not the SQL path — because the
diversification is the part where bugs hide; the over-fetch + metadata
hydration around it is straight DB plumbing.
"""
from __future__ import annotations

from repi.retrieval.diversify import diversify_by_service


def _cand(chunk_id: str, service: str, score: float):
    return {"chunk_id": chunk_id, "service": service, "score": score}


def test_returns_empty_for_empty_input():
    assert diversify_by_service([], top_k=10) == []


def test_returns_input_when_top_k_le_one():
    cands = [_cand("a", "svc-a", 1.0), _cand("b", "svc-b", 0.9)]
    assert diversify_by_service(cands, top_k=1) == [cands[0]]


def test_no_op_when_single_service_pool():
    """If filters pinned one service (or the corpus only has one), don't
    drop anything — diversification can't help and shouldn't hurt recall."""
    cands = [_cand(f"c{i}", "svc-a", 1.0 - i * 0.01) for i in range(10)]
    out = diversify_by_service(cands, top_k=5, cap_ratio=0.4)
    assert len(out) == 5
    assert [c["chunk_id"] for c in out] == ["c0", "c1", "c2", "c3", "c4"]


def test_demotes_over_represented_service():
    """8 from svc-a, 2 from svc-b. With cap_ratio=0.4 over top_k=10 →
    per_service_cap = 4. svc-b's hits get pulled into the top half of the
    returned slice instead of being buried at positions 8-9 (which is what
    plain RRF order would produce). Soft cap → all 10 candidates still
    appear; what changes is *where*."""
    cands = [_cand(f"a{i}", "svc-a", 0.9 - i * 0.01) for i in range(8)]
    cands += [_cand(f"b{i}", "svc-b", 0.5 - i * 0.01) for i in range(2)]

    out = diversify_by_service(cands, top_k=10, cap_ratio=0.4)
    svcs = [c["service"] for c in out]
    # Both svc-b hits land in the first 6 positions (cap=4 svc-a, then both
    # svc-b before the deferred svc-a backfill).
    assert svcs[:6].count("svc-b") == 2
    # In plain RRF order both svc-b hits would be at positions 8,9. The first
    # svc-b position should now be at most 4 — that's the reordering signal.
    assert svcs.index("svc-b") <= 4
    # And the soft cap doesn't drop anything — top_k filled.
    assert len(out) == 10


def test_relative_order_preserved_within_service():
    """Within a service, the higher-ranked candidate must come first
    regardless of whether it was picked in the cap pass or backfilled."""
    cands = [
        _cand("a1", "svc-a", 0.9),
        _cand("b1", "svc-b", 0.85),
        _cand("a2", "svc-a", 0.8),
        _cand("a3", "svc-a", 0.75),
        _cand("a4", "svc-a", 0.7),
    ]
    out = diversify_by_service(cands, top_k=4, cap_ratio=0.5)  # cap = 2
    a_order = [c["chunk_id"] for c in out if c["service"] == "svc-a"]
    # cap pass takes a1, a2 (count[svc-a] hits 2); b1 fills its quota;
    # backfill brings in a3. a4 doesn't fit in top_k=4.
    assert a_order == ["a1", "a2", "a3"]
    assert out[1]["chunk_id"] == "b1"  # svc-b promoted ahead of a2's defer pile


def test_handles_missing_service_key():
    """Candidates missing 'service' bucket together under __unknown__ so
    they don't all rank-1 themselves into the picked list."""
    cands = [
        {"chunk_id": "u1", "score": 1.0},
        {"chunk_id": "u2", "score": 0.9},
        {"chunk_id": "u3", "score": 0.8},
        _cand("a1", "svc-a", 0.7),
    ]
    out = diversify_by_service(cands, top_k=3, cap_ratio=0.34)  # cap = 2
    # Unknowns counted as one service → only 2 of them in cap pass,
    # then svc-a slots in, then 3rd unknown backfills.
    assert [c["chunk_id"] for c in out] == ["u1", "u2", "a1"]
