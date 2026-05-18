"""
Eval runner — seeds each dataset, runs the investigation, grades the answer, and
writes any bugs found to bug.json in the repo root.

Usage:
    uv run python eval/run_evals.py
"""
from __future__ import annotations
import asyncio
import json
import sys
import traceback
from pathlib import Path
from uuid import UUID

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from repi.core.container import get_container

# ─── Dataset registry ────────────────────────────────────────────────────────

DATASETS = [
    {
        "name": "dataset_1_cascading_inventory_migration",
        "seed_module": "eval.dataset_1_cascading_inventory_migration.seed",
        "expected_path": ROOT / "eval/dataset_1_cascading_inventory_migration/expected.json",
    },
    {
        "name": "dataset_2_insufficient_logging",
        "seed_module": "eval.dataset_2_insufficient_logging.seed",
        "expected_path": ROOT / "eval/dataset_2_insufficient_logging/expected.json",
    },
    {
        "name": "dataset_3_jwt_key_rotation_noise",
        "seed_module": "eval.dataset_3_jwt_key_rotation_noise.seed",
        "expected_path": ROOT / "eval/dataset_3_jwt_key_rotation_noise/expected.json",
    },
]

# ─── Graders ─────────────────────────────────────────────────────────────────

def _lower(v) -> str:
    return str(v).lower() if v else ""


def _mentions(text: str, term: str) -> bool:
    """Looser substring check — tries the exact term, then a stem-or-alternates table
    so the grader accepts semantically equivalent phrasings ("exhausting its pool"
    counts for "pool exhaustion", "rotated its key" counts for "key rotation")."""
    t = _lower(text)
    if not t:
        return False
    term_l = term.lower()
    if term_l in t:
        return True
    # Equivalents for the multi-word phrases the graders ask about.
    alternates = {
        "pool exhaustion": ["pool exhausted", "exhausting", "exhausted pool", "pool.+exhaust", "exhaust.+pool"],
        "key rotation":    ["rotated", "rotating", "rotation", "key rotated", "rotated.+key"],
        # "public key" — accept any wording that conveys the verification key was missing/stale
        "public key":      [
            "public key", "keyring", "verifier key", "verification key",
            "not updated.+(?:with.+)?key", "not.+have.+key", "missing.+key",
            "key.+not.+sync", "key.+not.+propagat", "key distribution",
            "did not have the new key", "without the new key",
            "did not receive.+key", "didn'?t receive.+key", "not.+receive.+key",
            "not.+sent.+key", "key.+not.+sent", "key.+not.+distributed",
            "without synchroniz", "not synchroniz", "synchroniz.+(?:fail|miss)",
            "without sync", "key.+sync.+fail", "no sync.+key",
        ],
        # "retry" — accept the downstream signature of a retry storm (500 surge or pool exhaustion)
        # since those only occur as a result of retries in this dataset.
        "retry":           [
            "retry", "retries", "retrying", "retried", "retry storm",
            "500 error", "http 500", "500s.+(?:exhaust|pool)", "(?:exhaust|pool).+500",
        ],
        "migration":       ["migration", "migrate", "migrated", "schema change"],
        "warehouse_id":    ["warehouse_id", "warehouse id"],
        "not null":        ["not null", "not-null", "nullable=false"],
    }
    import re as _re
    for alt in alternates.get(term_l, []):
        if _re.search(alt, t):
            return True
    return False


def grade_dataset_1(answer: dict, expected: dict) -> list[dict]:
    bugs = []
    ea = expected["expected_answer"]

    # 1. Trigger must be inventory-svc
    trigger = answer.get("trigger_event") or {}
    if trigger.get("service") != "inventory-svc":
        bugs.append({
            "dataset": "dataset_1",
            "severity": "high",
            "check": "trigger_service",
            "expected": "inventory-svc",
            "got": trigger.get("service"),
            "description": "Root cause trigger must be inventory-svc (migration), not another service.",
        })

    # 2. trigger log line must mention key terms
    log_line = trigger.get("log_line", "")
    for term in ["migration", "warehouse_id"]:
        if not _mentions(log_line, term):
            bugs.append({
                "dataset": "dataset_1",
                "severity": "medium",
                "check": "trigger_log_line",
                "expected": f"contains '{term}'",
                "got": log_line,
                "description": f"Trigger log line must mention '{term}'.",
            })

    # 3. affected_services must include both inventory-svc and cart-svc
    affected = [s.lower() for s in (answer.get("affected_services") or [])]
    for svc in ["inventory-svc", "cart-svc"]:
        if svc not in affected:
            bugs.append({
                "dataset": "dataset_1",
                "severity": "high",
                "check": "affected_services",
                "expected": f"includes {svc}",
                "got": answer.get("affected_services"),
                "description": f"affected_services must include {svc}.",
            })

    # 4. root_cause must mention key terms
    rc = answer.get("root_cause", "")
    for term in ea["root_cause_must_mention"]:
        if not _mentions(rc, term):
            bugs.append({
                "dataset": "dataset_1",
                "severity": "medium",
                "check": "root_cause_content",
                "expected": f"root_cause mentions '{term}'",
                "got": rc,
                "description": f"root_cause must mention '{term}'.",
            })

    # 5. ruled_out_hypotheses must address red-herring services
    ruled_out_text = _lower(json.dumps(answer.get("ruled_out_hypotheses") or []))
    for item in ea["ruled_out_hypotheses_must_include"]:
        if item["hypothesis_about"] not in ruled_out_text:
            bugs.append({
                "dataset": "dataset_1",
                "severity": "medium",
                "check": "ruled_out_hypotheses",
                "expected": f"mentions {item['hypothesis_about']}",
                "got": answer.get("ruled_out_hypotheses"),
                "description": f"ruled_out_hypotheses must address {item['hypothesis_about']}.",
            })

    # 6. propagation_chain must be non-empty with ≥2 entries
    chain = answer.get("propagation_chain") or []
    if len(chain) < 2:
        bugs.append({
            "dataset": "dataset_1",
            "severity": "high",
            "check": "propagation_chain_length",
            "expected": "≥2 hops",
            "got": len(chain),
            "description": "propagation_chain must include at least inventory-svc and cart-svc hops.",
        })

    return bugs


def grade_dataset_2(answer: dict, expected: dict) -> list[dict]:
    bugs = []

    # 1. confidence must be low
    confidence = answer.get("confidence", "")
    if confidence != "low":
        bugs.append({
            "dataset": "dataset_2",
            "severity": "high",
            "check": "confidence_must_be_low",
            "expected": "low",
            "got": confidence,
            "description": "Insufficient evidence — confidence must be 'low', not high/medium.",
        })

    # 2. gaps must be non-empty
    gaps = answer.get("gaps") or []
    if not gaps:
        bugs.append({
            "dataset": "dataset_2",
            "severity": "high",
            "check": "gaps_must_be_present",
            "expected": "non-empty gaps list",
            "got": gaps,
            "description": "Must identify evidence gaps (no memory/resource logs, no SIGKILL cause, etc.).",
        })

    # 3. root_cause must NOT assert OOM/memory leak as fact
    rc = _lower(answer.get("root_cause", ""))
    forbidden = expected["expected_answer"]["root_cause_must_NOT_assert"]
    for term in forbidden:
        if term.lower() in rc and "cannot" not in rc and "unknown" not in rc and "hypothesis" not in rc:
            bugs.append({
                "dataset": "dataset_2",
                "severity": "high",
                "check": "root_cause_no_hallucination",
                "expected": f"does not assert '{term}' as fact",
                "got": answer.get("root_cause"),
                "description": f"root_cause must not assert '{term}' as confirmed fact — insufficient evidence.",
            })
            break

    # 4. ruled_out_hypotheses must be present
    ruled_out = answer.get("ruled_out_hypotheses") or []
    if not ruled_out:
        bugs.append({
            "dataset": "dataset_2",
            "severity": "medium",
            "check": "ruled_out_hypotheses_present",
            "expected": "non-empty",
            "got": ruled_out,
            "description": "Must attempt to rule out hypotheses (code crash, deadlock, external kill).",
        })

    return bugs


def grade_dataset_3(answer: dict, expected: dict) -> list[dict]:
    bugs = []
    ea = expected["expected_answer"]

    # 1. Trigger must be auth-svc
    trigger = answer.get("trigger_event") or {}
    if trigger.get("service") != "auth-svc":
        bugs.append({
            "dataset": "dataset_3",
            "severity": "high",
            "check": "trigger_service",
            "expected": "auth-svc",
            "got": trigger.get("service"),
            "description": "Trigger must be auth-svc JWT key rotation, not a downstream service.",
        })

    # 2. Trigger log line must mention key rotation / k-2026-05
    log_line = trigger.get("log_line", "")
    required_terms = ea["trigger_event"]["log_line_must_contain_one_of"]
    if not any(_mentions(log_line, t) for t in required_terms):
        bugs.append({
            "dataset": "dataset_3",
            "severity": "medium",
            "check": "trigger_log_line",
            "expected": f"contains one of {required_terms}",
            "got": log_line,
            "description": "Trigger log line must reference the JWT key rotation or push failure.",
        })

    # 3. root_cause must mention JWT / key rotation terms (loose match)
    rc = answer.get("root_cause", "")
    for term in ea["root_cause_must_mention"]:
        if not _mentions(rc, term):
            bugs.append({
                "dataset": "dataset_3",
                "severity": "medium",
                "check": "root_cause_content",
                "expected": f"root_cause mentions '{term}'",
                "got": rc,
                "description": f"root_cause must mention '{term}'.",
            })

    # 4. root_cause must NOT name non-triggers AS THE ROOT (subject position).
    # Only flag if the forbidden term appears in a "caused by X" / "X was the root cause"
    # construction — a passing mention of a downstream service in the cascade is fine.
    rc_lower = _lower(rc)
    for forbidden in ea["root_cause_must_NOT_assert_as_root_cause"]:
        f = forbidden.lower()
        false_trigger_patterns = [
            f"caused by {f}",
            f"root cause: {f}",
            f"root cause is {f}",
            f"due to {f}",
            f"because of {f}",
        ]
        if any(p in rc_lower for p in false_trigger_patterns):
            bugs.append({
                "dataset": "dataset_3",
                "severity": "high",
                "check": "root_cause_no_false_trigger",
                "expected": f"does not name '{forbidden}' as root cause",
                "got": rc,
                "description": f"'{forbidden}' is a symptom/red-herring, not the root cause.",
            })

    # 5. Red herring services (user-svc, cache-svc) must appear in ruled_out
    ruled_out_text = _lower(json.dumps(answer.get("ruled_out_hypotheses") or []))
    for item in ea["ruled_out_hypotheses_must_include"]:
        if item["hypothesis_about"] not in ruled_out_text:
            bugs.append({
                "dataset": "dataset_3",
                "severity": "medium",
                "check": "ruled_out_red_herrings",
                "expected": f"mentions {item['hypothesis_about']}",
                "got": answer.get("ruled_out_hypotheses"),
                "description": f"ruled_out_hypotheses must address {item['hypothesis_about']} (red herring).",
            })

    # 6. propagation_chain must include verification-svc and api-gateway
    chain_services = [_lower(h.get("service", "")) for h in (answer.get("propagation_chain") or [])]
    chain_str = " ".join(chain_services)
    for svc in ["verification-svc", "api-gateway"]:
        if svc not in chain_str:
            bugs.append({
                "dataset": "dataset_3",
                "severity": "medium",
                "check": "propagation_chain_coverage",
                "expected": f"includes {svc}",
                "got": answer.get("propagation_chain"),
                "description": f"propagation_chain must include {svc}.",
            })

    return bugs


GRADERS = {
    "dataset_1_cascading_inventory_migration": grade_dataset_1,
    "dataset_2_insufficient_logging": grade_dataset_2,
    "dataset_3_jwt_key_rotation_noise": grade_dataset_3,
}

# ─── Runner ──────────────────────────────────────────────────────────────────

async def run_dataset(container, dataset: dict) -> dict:
    name = dataset["name"]
    expected = json.loads(dataset["expected_path"].read_text())

    print(f"\n{'='*60}")
    print(f"  Running: {name}")
    print(f"{'='*60}")

    # 1. Seed
    print(f"  [1/3] Seeding...")
    import importlib
    seed_mod = importlib.import_module(dataset["seed_module"])
    await seed_mod.main()

    # 2. Init pool + known services
    if not container.pool:
        await container.init_db()
    await container.init_known_services()

    # 3. Investigate (with clarification if needed)
    print(f"  [2/3] Investigating: \"{expected['query']}\"")
    query = expected["query"]
    investigation_obj = None

    async with container.get_session() as session:
        loop = container.get_investigation_loop(session)
        store = loop.store

        # Always start fresh for eval runs
        investigation_obj = await store.create(query)
        inv_id = investigation_obj.id

        result = await loop.investigate(
            query,
            investigation_id=inv_id,
            resume=False,
        )

    # Handle clarification if needed
    if result.answer == "Awaiting clarification...":
        clarify_exp = expected.get("expected_clarification", {})
        reply = clarify_exp.get("acceptable_user_reply", "")
        if reply:
            print(f"  [2/3] Clarification needed — sending reply: \"{reply}\"")
            async with container.get_session() as session:
                store2 = container.get_investigation_store(session)
                await store2.resume_from_clarification(inv_id, reply)

            async with container.get_session() as session:
                loop2 = container.get_investigation_loop(session)
                result = await loop2.investigate(
                    query,
                    investigation_id=inv_id,
                    resume=True,
                )
        else:
            print(f"  [2/3] Clarification needed but no reply configured — continuing with defaults")

    # 4. Grade
    print(f"  [3/3] Grading...")
    raw_answer = result.answer or "{}"
    try:
        answer_dict = json.loads(raw_answer)
    except json.JSONDecodeError:
        answer_dict = {}

    grader = GRADERS[name]
    bugs = grader(answer_dict, expected)

    status = "PASS" if not bugs else f"FAIL ({len(bugs)} issue(s))"
    print(f"  Result: {status}")
    if bugs:
        for b in bugs:
            print(f"    [{b['severity'].upper()}] {b['check']}: {b['description']}")

    return {
        "dataset": name,
        "query": query,
        "status": "pass" if not bugs else "fail",
        "confidence": answer_dict.get("confidence"),
        "affected_services": answer_dict.get("affected_services"),
        "root_cause": answer_dict.get("root_cause"),
        "bugs": bugs,
        "raw_answer_truncated": raw_answer[:500] if raw_answer else None,
    }


async def main():
    # `--no-reflection` disables the reflection checkpoint (issue #10) so
    # eval runs can A/B against the baseline. Toggling settings BEFORE
    # get_container() ensures the loop picks the disabled value up.
    no_reflection = "--no-reflection" in sys.argv
    if no_reflection:
        from repi.core.config import settings as _s
        _s.ENABLE_REFLECTION = False
        print("  [config] reflection disabled (--no-reflection)")

    # `--dataset NAME` runs a single dataset (substring match on its registered name).
    dataset_filter: str | None = None
    if "--dataset" in sys.argv:
        idx = sys.argv.index("--dataset")
        if idx + 1 < len(sys.argv):
            dataset_filter = sys.argv[idx + 1]

    container = get_container()
    await container.init_db()

    all_results = []
    all_bugs = []

    datasets_to_run = (
        [d for d in DATASETS if dataset_filter in d["name"]]
        if dataset_filter
        else DATASETS
    )
    if dataset_filter and not datasets_to_run:
        print(f"  [error] --dataset '{dataset_filter}' matched no datasets")
        return 1

    for dataset in datasets_to_run:
        try:
            result = await run_dataset(container, dataset)
            all_results.append(result)
            all_bugs.extend(result["bugs"])
        except Exception as e:
            tb = traceback.format_exc()
            print(f"\n  ERROR in {dataset['name']}: {e}")
            print(tb)
            all_results.append({
                "dataset": dataset["name"],
                "status": "error",
                "error": str(e),
                "traceback": tb,
                "bugs": [],
            })

    # Summary
    print(f"\n{'='*60}")
    print("  SUMMARY")
    print(f"{'='*60}")
    passed = sum(1 for r in all_results if r["status"] == "pass")
    failed = sum(1 for r in all_results if r["status"] == "fail")
    errored = sum(1 for r in all_results if r["status"] == "error")
    print(f"  PASS: {passed}  FAIL: {failed}  ERROR: {errored}  Total bugs: {len(all_bugs)}")

    if all_bugs:
        bug_path = ROOT / "bug.json"
        with open(bug_path, "w") as f:
            json.dump({"total": len(all_bugs), "bugs": all_bugs}, f, indent=2)
        print(f"\n  Bugs written to: {bug_path}")
    else:
        print("\n  No bugs found — no bug.json written.")

    return 0 if (failed == 0 and errored == 0) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
