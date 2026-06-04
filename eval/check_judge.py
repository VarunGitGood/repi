"""
Hard-test the LLM judge with canned gold + fail answers per dataset.

For each dataset we hand-craft two answers:
- gold: aligns with expected.json — judge should score >= 0.8
- fail: embodies one of the dataset's `common_failure_modes_to_grade_against`
        — judge should score <= 0.5

Prints a verdict table. Exit 0 if every row passes both thresholds, else 1.

Usage:
    uv run python eval/check_judge.py
    uv run python eval/check_judge.py --judge-provider openai --judge-model gpt-4o
"""
from __future__ import annotations
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from eval.judge import LLMJudge
from eval.run_evals import create_judge, _parse_args  # reuse selector + arg parsing


GOLD_PASS_THRESHOLD = 0.8
FAIL_MAX_THRESHOLD = 0.5


# ─── Canned answers per dataset ──────────────────────────────────────────────
#
# Each block has:
#   - dataset_name (folder name, matches DATASETS in run_evals.py)
#   - expected_path
#   - gold: a hand-crafted answer that satisfies expected.json's criteria
#   - fail: a hand-crafted answer that exhibits one entry from
#           common_failure_modes_to_grade_against (named in fail_mode_note)

CANNED_CASES = [
    {
        "dataset_name": "dataset_1_cascading_inventory_migration",
        "expected_path": ROOT / "eval/dataset_1_cascading_inventory_migration/expected.json",
        "gold": {
            "trigger_event": {
                "service": "inventory-svc",
                "timestamp": "2026-05-01T22:00:14Z",
                "log_line": "Migration 0042 added column warehouse_id NOT NULL to skus table",
            },
            "root_cause": (
                "Migration 0042 added a NOT NULL warehouse_id column to the skus table "
                "in inventory-svc. Existing INSERTs that did not supply warehouse_id "
                "started failing with constraint violations, returning 500s. cart-svc "
                "retried aggressively, exhausting its connection pool, which in turn "
                "caused checkout/cart timeouts downstream."
            ),
            "affected_services": ["inventory-svc", "cart-svc"],
            "propagation_chain": [
                {"service": "inventory-svc", "ts": "2026-05-01T22:00:14Z", "what": "migration 0042 added warehouse_id NOT NULL to skus table"},
                {"service": "inventory-svc", "ts": "2026-05-01T22:00:47Z", "what": "500 returned: null value in warehouse_id column"},
                {"service": "cart-svc",      "ts": "2026-05-01T22:00:50Z", "what": "retry loop triggered against inventory-svc"},
                {"service": "cart-svc",      "ts": "2026-05-01T22:04:11Z", "what": "connection pool exhausted under retry storm"},
                {"service": "cart-svc",      "ts": "2026-05-01T22:04:15Z", "what": "checkout / cart timeout to clients"},
            ],
            "ruled_out_hypotheses": [
                {"hypothesis_about": "pricing-svc", "rationale": "pricing-svc shows no ERROR/WARNING lines in window beyond reduced inbound rate."},
                {"hypothesis_about": "payment-svc", "rationale": "payment-svc only observed reduced inbound checkout rate — a downstream symptom, no errors."},
                {"hypothesis_about": "notification-svc", "rationale": "notification-svc had no errors and is not in the cart→inventory path."},
            ],
            "confidence": "high",
            "gaps": [],
            "assumptions": [
                "'friday night' interpreted as 2026-05-01 22:00 to 2026-05-02 06:00 UTC",
                "'checkout' interpreted as cart-svc",
            ],
            "incident_window": {"start": "2026-05-01T22:00:00Z", "end": "2026-05-01T22:36:00Z"},
        },
        "fail_mode_note": "names cart-svc as root cause (dominant symptom, not trigger)",
        "fail": {
            "trigger_event": {
                "service": "cart-svc",
                "timestamp": "2026-05-01T22:04:11Z",
                "log_line": "Connection pool exhausted",
            },
            "root_cause": (
                "cart-svc exhausted its database connection pool, which caused "
                "checkout timeouts. This is the root cause of the incident."
            ),
            "affected_services": ["cart-svc", "pricing-svc"],
            "propagation_chain": [
                {"service": "cart-svc", "ts": "2026-05-01T22:04:11Z", "what": "pool exhausted"},
                {"service": "cart-svc", "ts": "2026-05-01T22:04:15Z", "what": "checkout timeout"},
            ],
            "ruled_out_hypotheses": [],
            "confidence": "high",
            "gaps": [],
            "assumptions": [],
            "incident_window": {"start": "2026-05-01T22:04:00Z", "end": "2026-05-01T22:30:00Z"},
        },
    },
    {
        "dataset_name": "dataset_2_insufficient_logging",
        "expected_path": ROOT / "eval/dataset_2_insufficient_logging/expected.json",
        "gold": {
            "trigger_event": {
                "service": "report-svc",
                "timestamp": "2026-04-30T03:14:48Z",
                "log_line": "Process received SIGKILL",
            },
            "root_cause": (
                "Root cause cannot be determined from available logs. report-svc "
                "was terminated by SIGKILL, which is consistent with several "
                "hypotheses (OOM kill, manual external kill, orchestrator action) "
                "but none can be confirmed without memory, GC, or signal-source "
                "telemetry that is absent from the captured logs."
            ),
            "affected_services": ["report-svc", "cron-runner"],
            "propagation_chain": [
                {"service": "report-svc", "ts": "2026-04-30T03:14:48Z", "what": "SIGKILL received, process terminated"},
                {"service": "cron-runner", "ts": "2026-04-30T03:15:00Z", "what": "exceeded timeout, job marked failed"},
            ],
            "ruled_out_hypotheses": [
                {"hypothesis_about": "code crash", "rationale": "weakly ruled out — no stack trace or panic logged before SIGKILL"},
                {"hypothesis_about": "deadlock", "rationale": "cannot confirm or rule out — no thread-state logs"},
                {"hypothesis_about": "external kill", "rationale": "consistent with SIGKILL but cannot identify the killer"},
            ],
            "confidence": "low",
            "gaps": [
                "no memory or resource utilization logs",
                "no per-request or per-stage timing logs from report-svc",
                "no logs identifying which process or system signaled SIGKILL",
            ],
            "assumptions": [
                "interpreted 'last night around 3am' → 2026-04-30 02:00–04:00 UTC",
            ],
            "incident_window": {"start": "2026-04-30T02:00:00Z", "end": "2026-04-30T03:45:00Z"},
        },
        "fail_mode_note": "asserts OOM/memory leak with confidence=high",
        "fail": {
            "trigger_event": {
                "service": "report-svc",
                "timestamp": "2026-04-30T03:14:48Z",
                "log_line": "Process received SIGKILL",
            },
            "root_cause": (
                "report-svc has a memory leak in the report-generation code path, "
                "causing the kernel to OOM-kill the process. GC pressure built up "
                "until the process exhausted its memory budget and was terminated."
            ),
            "affected_services": ["report-svc", "cron-runner"],
            "propagation_chain": [
                {"service": "report-svc", "ts": "2026-04-30T03:14:48Z", "what": "OOM-killed due to memory leak"},
                {"service": "cron-runner", "ts": "2026-04-30T03:15:00Z", "what": "job timeout"},
            ],
            "ruled_out_hypotheses": [],
            "confidence": "high",
            "gaps": [],
            "assumptions": [],
            "incident_window": {"start": "2026-04-30T02:00:00Z", "end": "2026-04-30T03:45:00Z"},
        },
    },
    {
        "dataset_name": "dataset_3_jwt_key_rotation_noise",
        "expected_path": ROOT / "eval/dataset_3_jwt_key_rotation_noise/expected.json",
        "gold": {
            "trigger_event": {
                "service": "auth-svc",
                "timestamp": "2026-05-04T09:15:02Z",
                "log_line": "JWT key rotation triggered, key_id=k-2026-05; public key push to verification-svc timed out",
            },
            "root_cause": (
                "auth-svc performed a JWT signing-key rotation to k-2026-05. The "
                "public-key push to verification-svc timed out, so verification-svc "
                "never learned about the new key. Every JWT signed with k-2026-05 "
                "was therefore rejected as having an unknown key_id, surfacing as "
                "401s at the api-gateway and breaking downstream services like "
                "billing-svc."
            ),
            "affected_services": ["auth-svc", "verification-svc", "api-gateway", "billing-svc"],
            "propagation_chain": [
                {"service": "auth-svc", "ts": "2026-05-04T09:15:02Z", "what": "key rotation to k-2026-05; public key push timed out"},
                {"service": "verification-svc", "ts": "2026-05-04T09:15:30Z", "what": "rejected token: unknown key_id=k-2026-05"},
                {"service": "api-gateway", "ts": "2026-05-04T09:15:35Z", "what": "returning 401 for failed JWT verification"},
                {"service": "billing-svc", "ts": "2026-05-04T09:15:42Z", "what": "checkout failed: 401 from upstream"},
            ],
            "ruled_out_hypotheses": [
                {"hypothesis_about": "user-svc", "rationale": "user-svc slow-query warning at 09:15:10 is a read-path anomaly on a separate service with no link to JWT verification."},
                {"hypothesis_about": "cache-svc", "rationale": "cache-svc eviction spike predates the incident and the JWT verification path does not depend on cache-svc."},
            ],
            "confidence": "high",
            "gaps": [],
            "assumptions": [
                "'last monday morning' interpreted as 2026-05-04 06:00–12:00 UTC",
            ],
            "incident_window": {"start": "2026-05-04T09:15:00Z", "end": "2026-05-04T09:45:00Z"},
        },
        "fail_mode_note": "names api-gateway/billing-svc as root cause; includes cache-svc/user-svc as affected",
        "fail": {
            "trigger_event": {
                "service": "api-gateway",
                "timestamp": "2026-05-04T09:15:35Z",
                "log_line": "401 Unauthorized",
            },
            "root_cause": (
                "api-gateway started rejecting requests with 401s, which broke "
                "billing-svc checkout. The most likely cause is cache-svc eviction "
                "pressure combined with a user-svc slow query that destabilised the "
                "auth path."
            ),
            "affected_services": ["api-gateway", "billing-svc", "cache-svc", "user-svc"],
            "propagation_chain": [
                {"service": "api-gateway", "ts": "2026-05-04T09:15:35Z", "what": "401s started"},
                {"service": "billing-svc", "ts": "2026-05-04T09:15:42Z", "what": "checkout failed"},
            ],
            "ruled_out_hypotheses": [],
            "confidence": "high",
            "gaps": [],
            "assumptions": [],
            "incident_window": {"start": "2026-05-04T09:15:00Z", "end": "2026-05-04T09:45:00Z"},
        },
    },
]


# ─── Runner ──────────────────────────────────────────────────────────────────


async def _score_one(judge: LLMJudge, dataset_name: str, expected: dict, answer: dict) -> tuple[float, list]:
    result = await judge.score(
        answer=answer,
        expected=expected,
        dataset_name=dataset_name,
        model_under_test="canned",
    )
    return result.aggregate_score, result.criteria


def _verdict(gold_score: float, fail_score: float) -> tuple[bool, str]:
    gold_ok = gold_score >= GOLD_PASS_THRESHOLD
    fail_ok = fail_score <= FAIL_MAX_THRESHOLD
    ok = gold_ok and fail_ok
    bits = []
    if not gold_ok:
        bits.append("gold-too-low")
    if not fail_ok:
        bits.append("fail-too-high")
    return ok, ("✓" if ok else "✗ " + ",".join(bits))


async def main() -> int:
    args = _parse_args(sys.argv[1:])

    from repi.core.config import settings as _settings
    mut_provider = _settings.LLM_PROVIDER
    judge = create_judge(args, mut_provider_name=mut_provider)
    print(f"  [config] judge model: {judge.model_name}")
    print(f"  Thresholds: gold >= {GOLD_PASS_THRESHOLD}, fail <= {FAIL_MAX_THRESHOLD}\n")

    rows: list[dict] = []
    all_ok = True

    for case in CANNED_CASES:
        name = case["dataset_name"]
        expected = json.loads(case["expected_path"].read_text())

        print(f"  [scoring] {name} — gold + fail")
        gold_score, gold_criteria = await _score_one(judge, name, expected, case["gold"])
        fail_score, fail_criteria = await _score_one(judge, name, expected, case["fail"])
        ok, verdict_str = _verdict(gold_score, fail_score)
        if not ok:
            all_ok = False

        rows.append({
            "dataset": name,
            "gold_score": gold_score,
            "fail_score": fail_score,
            "ok": ok,
            "verdict": verdict_str,
            "fail_mode_note": case["fail_mode_note"],
            "gold_criteria": gold_criteria,
            "fail_criteria": fail_criteria,
        })

    # Verdict table
    print("\n" + "=" * 100)
    print(f"  {'dataset':<48s} {'gold':>8s} {'fail':>8s}   verdict")
    print("=" * 100)
    for r in rows:
        print(
            f"  {r['dataset']:<48s} {r['gold_score']:>8.2f} {r['fail_score']:>8.2f}   {r['verdict']}"
        )

    # For each ✗ row, dump per-criterion breakdown so the user knows which
    # criterion is miscalibrated.
    for r in rows:
        if r["ok"]:
            continue
        print(f"\n  [miscalibrated] {r['dataset']}")
        print(f"    fail mode tested: {r['fail_mode_note']}")
        print("    gold per-criterion:")
        for c in r["gold_criteria"]:
            indicator = " " if c.score >= GOLD_PASS_THRESHOLD else "!"
            print(f"      {indicator} {c.name:<28s} {c.score:.2f}  {c.explanation[:120]}")
        print("    fail per-criterion:")
        for c in r["fail_criteria"]:
            indicator = " " if c.score <= FAIL_MAX_THRESHOLD else "!"
            print(f"      {indicator} {c.name:<28s} {c.score:.2f}  {c.explanation[:120]}")

    print()
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
