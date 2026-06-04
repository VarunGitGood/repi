"""Extracts scoring criteria from an expected.json dict into a structured text
block that the LLM judge can evaluate against.

Each expected.json already encodes what a correct answer looks like via
well-known keys (trigger_event, root_cause_must_mention, etc.). This module
reads those keys and assembles a human-readable criteria description — no
per-dataset code paths, no regex tables.
"""
from __future__ import annotations
import json


_CRITERION_BUILDERS: list[tuple[str, str]] = [
    ("trigger_identification", "_trigger_criterion"),
    ("root_cause_accuracy", "_root_cause_criterion"),
    ("propagation_chain", "_propagation_criterion"),
    ("red_herring_handling", "_red_herring_criterion"),
    ("confidence_calibration", "_confidence_criterion"),
    ("gap_awareness", "_gap_criterion"),
    ("hallucination_avoidance", "_hallucination_criterion"),
]


def build_criteria(expected: dict, only_names: list[str] | None = None) -> str:
    ea = expected.get("expected_answer", {})
    sections: list[str] = []

    builders_by_name = {
        "_trigger_criterion": _trigger_criterion,
        "_root_cause_criterion": _root_cause_criterion,
        "_propagation_criterion": _propagation_criterion,
        "_red_herring_criterion": _red_herring_criterion,
        "_confidence_criterion": _confidence_criterion,
        "_gap_criterion": _gap_criterion,
        "_hallucination_criterion": _hallucination_criterion,
    }

    for name, builder_name in _CRITERION_BUILDERS:
        if only_names is not None and name not in only_names:
            continue
        section = builders_by_name[builder_name](ea)
        if section:
            sections.append(section)

    return "\n\n".join(sections)


def active_criterion_names(expected: dict) -> list[str]:
    """Return the criterion names that apply to this dataset."""
    ea = expected.get("expected_answer", {})
    names: list[str] = []

    if ea.get("trigger_event") or ea.get("trigger_event_acceptable_options"):
        names.append("trigger_identification")

    if ea.get("root_cause_must_mention") or ea.get("root_cause_must_be_one_of"):
        names.append("root_cause_accuracy")

    if ea.get("propagation_chain_must_include_in_order"):
        names.append("propagation_chain")

    if ea.get("ruled_out_hypotheses_must_include") or ea.get("ruled_out_hypotheses_must_consider"):
        names.append("red_herring_handling")

    if ea.get("confidence"):
        names.append("confidence_calibration")

    if ea.get("gaps_must_include_one_of"):
        names.append("gap_awareness")

    if ea.get("root_cause_must_NOT_assert") or ea.get("root_cause_must_NOT_assert_as_root_cause"):
        names.append("hallucination_avoidance")

    return names


def _trigger_criterion(ea: dict) -> str:
    trigger = ea.get("trigger_event")
    trigger_options = ea.get("trigger_event_acceptable_options")

    if trigger:
        lines = ["## Criterion: trigger_identification"]
        lines.append(f"The trigger service MUST be: {trigger.get('service', 'N/A')}")
        contain = trigger.get("log_line_must_contain")
        contain_one = trigger.get("log_line_must_contain_one_of")
        if contain:
            lines.append(f"The trigger log line must reference: \"{contain}\"")
        if contain_one:
            lines.append(f"The trigger log line must reference one of: {json.dumps(contain_one)}")
        return "\n".join(lines)

    if trigger_options:
        lines = ["## Criterion: trigger_identification"]
        lines.append("Acceptable trigger events (any one is correct):")
        for opt in trigger_options:
            svc = opt.get("service", "?")
            note = opt.get("note", "")
            contain = opt.get("log_line_must_contain", "")
            lines.append(f"  - service={svc}, log must mention \"{contain}\". Note: {note}")
        return "\n".join(lines)

    return ""


def _root_cause_criterion(ea: dict) -> str:
    must_mention = ea.get("root_cause_must_mention")
    must_be_one_of = ea.get("root_cause_must_be_one_of")

    if not must_mention and not must_be_one_of:
        return ""

    lines = ["## Criterion: root_cause_accuracy"]
    if must_mention:
        lines.append("The root_cause explanation must mention ALL of these concepts (semantic match, not exact string):")
        for term in must_mention:
            lines.append(f"  - {term}")
    if must_be_one_of:
        lines.append(f"The root_cause must be one of: {json.dumps(must_be_one_of)}")
        lines.append("The answer must NOT assert a specific root cause as fact when evidence is insufficient.")
    return "\n".join(lines)


def _propagation_criterion(ea: dict) -> str:
    chain = ea.get("propagation_chain_must_include_in_order")
    if not chain:
        return ""

    lines = ["## Criterion: propagation_chain"]
    lines.append("The propagation_chain must include these hops in causal order:")
    for hop in chain:
        svc = hop.get("service", "?")
        what = hop.get("what_must_mention", "")
        lines.append(f"  - {svc}: must mention \"{what}\"")
    return "\n".join(lines)


def _red_herring_criterion(ea: dict) -> str:
    must_include = ea.get("ruled_out_hypotheses_must_include")
    must_consider = ea.get("ruled_out_hypotheses_must_consider")

    if not must_include and not must_consider:
        return ""

    lines = ["## Criterion: red_herring_handling"]

    if must_include:
        lines.append("The ruled_out_hypotheses must address these red herrings:")
        for item in must_include:
            about = item.get("hypothesis_about", "?")
            rationale = item.get("rationale", "")
            lines.append(f"  - {about}: {rationale}")

    if must_consider:
        lines.append("The ruled_out_hypotheses must consider these possibilities:")
        for item in must_consider:
            about = item.get("hypothesis_about", "?")
            expected = item.get("expected", "")
            lines.append(f"  - {about}: {expected}")

    return "\n".join(lines)


def _confidence_criterion(ea: dict) -> str:
    confidence = ea.get("confidence")
    if not confidence:
        return ""

    lines = ["## Criterion: confidence_calibration"]
    lines.append(f"The confidence level MUST be: {confidence}")
    if confidence == "low":
        lines.append("This dataset has insufficient evidence — high or medium confidence is a hallucination.")
    return "\n".join(lines)


def _gap_criterion(ea: dict) -> str:
    gaps = ea.get("gaps_must_include_one_of")
    if not gaps:
        return ""

    lines = ["## Criterion: gap_awareness"]
    lines.append("The gaps list must include at least one of:")
    for gap in gaps:
        lines.append(f"  - \"{gap}\"")
    return "\n".join(lines)


def _hallucination_criterion(ea: dict) -> str:
    not_assert = ea.get("root_cause_must_NOT_assert")
    not_assert_root = ea.get("root_cause_must_NOT_assert_as_root_cause")

    if not not_assert and not not_assert_root:
        return ""

    lines = ["## Criterion: hallucination_avoidance"]
    if not_assert:
        lines.append("The root_cause must NOT assert any of these as confirmed fact:")
        for term in not_assert:
            lines.append(f"  - \"{term}\"")
    if not_assert_root:
        lines.append("The root_cause must NOT name any of these as THE root cause (mentioning them as downstream effects is fine):")
        for term in not_assert_root:
            lines.append(f"  - \"{term}\"")
    return "\n".join(lines)
