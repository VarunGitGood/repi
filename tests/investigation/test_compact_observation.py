"""_compact_observation caps what a tool result contributes to the LLM
conversation. Tool results are re-sent on every subsequent turn, so uncapped
observations multiply across the loop — the main driver of token-per-minute
429s. The DB/ledger keep the full result; only the conversation is clipped.
"""
import json

from repi.investigation.react_loop import ReactInvestigationLoop

_compact = ReactInvestigationLoop._compact_observation


def test_short_result_passes_through_unchanged():
    result = {"logs": [{"chunk_id": "a", "text": "short"}], "count": 1}
    assert json.loads(_compact(result)) == result


def test_long_list_clipped_with_explicit_marker():
    result = {"logs": [{"chunk_id": str(i), "text": f"line {i}"} for i in range(50)]}
    out = json.loads(_compact(result))
    # 10 kept + 1 truncation marker
    assert len(out["logs"]) == ReactInvestigationLoop.MAX_OBS_ITEMS + 1
    assert "40 more items truncated" in out["logs"][-1]


def test_long_text_field_clipped():
    result = {"text": "x" * 5000}
    out = json.loads(_compact(result))
    assert len(out["text"]) < 400
    assert out["text"].endswith("...[truncated]")


def test_nested_lists_clipped_too():
    result = {"services": [{"logs": [{"text": "y" * 1000}] * 30}]}
    out = json.loads(_compact(result))
    inner = out["services"][0]["logs"]
    assert len(inner) == ReactInvestigationLoop.MAX_OBS_ITEMS + 1


def test_oversized_result_falls_back_to_tighter_caps_and_stays_valid_json():
    # Many medium-sized entries: per-field caps alone exceed the total cap.
    result = {f"key{i}": [{"text": "z" * 299} for _ in range(10)] for i in range(20)}
    s = _compact(result)
    assert len(s) <= ReactInvestigationLoop.MAX_OBS_TOTAL_CHARS + 2000  # tight-cap pass, not a hard slice
    json.loads(s)  # must be valid JSON, never a sliced string


def test_input_not_mutated():
    result = {"logs": [{"text": "x" * 5000}] * 20}
    _compact(result)
    assert len(result["logs"]) == 20
    assert len(result["logs"][0]["text"]) == 5000
