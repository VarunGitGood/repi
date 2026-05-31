"""
Eval runner — seeds each dataset, runs the investigation, scores the answer
with an LLM judge, and writes results to bug.json in the repo root.

Usage:
    uv run python eval/run_evals.py
    uv run python eval/run_evals.py --dataset dataset_1
    uv run python eval/run_evals.py --judge-provider openai --judge-model gpt-4o
    uv run python eval/run_evals.py --no-reflection
"""
from __future__ import annotations
import asyncio
import json
import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from repi.core.container import get_container
from eval.judge import LLMJudge, deterministic_precheck, PASS_THRESHOLD
from eval.results import JudgeResult

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

# ─── CLI arg parsing ────────────────────────────────────────────────────────

def _parse_args(argv: list[str]) -> dict:
    args: dict = {}
    i = 0
    while i < len(argv):
        if argv[i] == "--no-reflection":
            args["no_reflection"] = True
        elif argv[i] == "--dataset" and i + 1 < len(argv):
            args["dataset_filter"] = argv[i + 1]
            i += 1
        elif argv[i] == "--judge-provider" and i + 1 < len(argv):
            args["judge_provider"] = argv[i + 1]
            i += 1
        elif argv[i] == "--judge-model" and i + 1 < len(argv):
            args["judge_model"] = argv[i + 1]
            i += 1
        elif argv[i] == "--judge-api-key" and i + 1 < len(argv):
            args["judge_api_key"] = argv[i + 1]
            i += 1
        i += 1
    return args


def _create_judge(args: dict) -> LLMJudge:
    """Create the judge LLM provider from CLI args or fall back to config."""
    judge_provider_name = args.get("judge_provider")

    if judge_provider_name:
        from repi.llm.adapters import (
            OpenAIProvider, AnthropicProvider, MistralProvider,
            GeminiProvider, OllamaProvider,
        )
        api_key = args.get("judge_api_key", "")
        model = args.get("judge_model")

        providers = {
            "openai": lambda: OpenAIProvider(api_key=api_key, model=model or "gpt-4o"),
            "anthropic": lambda: AnthropicProvider(api_key=api_key, model=model or "claude-3-5-sonnet-20240620"),
            "mistral": lambda: MistralProvider(api_key=api_key, model=model or "mistral-large-latest"),
            "gemini": lambda: GeminiProvider(api_key=api_key, model=model or "gemini-1.5-pro"),
            "ollama": lambda: OllamaProvider(model=model or "mistral"),
        }
        factory = providers.get(judge_provider_name.lower())
        if not factory:
            raise ValueError(f"Unknown judge provider: {judge_provider_name}")
        return LLMJudge(factory())

    from repi.llm.factory import create_provider_from_env
    llm = create_provider_from_env()

    if args.get("judge_model"):
        from repi.llm.adapters import (
            OpenAIProvider, AnthropicProvider, MistralProvider,
            GeminiProvider, OllamaProvider,
        )
        model = args["judge_model"]
        if isinstance(llm, OpenAIProvider):
            llm = OpenAIProvider(api_key=llm._api_key, model=model)
        elif isinstance(llm, AnthropicProvider):
            llm = AnthropicProvider(api_key=llm._api_key, model=model)
        elif isinstance(llm, MistralProvider):
            llm = MistralProvider(api_key=llm._api_key, model=model)
        elif isinstance(llm, GeminiProvider):
            llm = GeminiProvider(api_key=llm._api_key, model=model)
        elif isinstance(llm, OllamaProvider):
            llm = OllamaProvider(base_url=llm._base_url, model=model)

    return LLMJudge(llm)

# ─── Runner ──────────────────────────────────────────────────────────────────

async def run_dataset(container, dataset: dict, judge: LLMJudge) -> dict:
    name = dataset["name"]
    expected = json.loads(dataset["expected_path"].read_text())

    print(f"\n{'='*60}")
    print(f"  Running: {name}")
    print(f"{'='*60}")

    # 1. Seed
    print(f"  [1/4] Seeding...")
    import importlib
    seed_mod = importlib.import_module(dataset["seed_module"])
    await seed_mod.main()

    # 2. Init pool + known services
    if not container.pool:
        await container.init_db()
    await container.init_known_services()

    # 3. Investigate (with clarification if needed)
    print(f"  [2/4] Investigating: \"{expected['query']}\"")
    query = expected["query"]

    async with container.get_session() as session:
        loop = container.get_investigation_loop(session)
        store = loop.store
        investigation_obj = await store.create(query)
        inv_id = investigation_obj.id

        result = await loop.investigate(
            query,
            investigation_id=inv_id,
            resume=False,
        )

    if result.answer == "Awaiting clarification...":
        clarify_exp = expected.get("expected_clarification", {})
        reply = clarify_exp.get("acceptable_user_reply", "")
        if reply:
            print(f"  [2/4] Clarification needed — sending reply: \"{reply}\"")
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
            print(f"  [2/4] Clarification needed but no reply configured — continuing with defaults")

    # 4. Parse answer
    print(f"  [3/4] Parsing answer...")
    raw_answer = result.answer or "{}"
    try:
        answer_dict = json.loads(raw_answer)
    except json.JSONDecodeError:
        answer_dict = {}

    # 5. Deterministic pre-check
    precheck_errors = deterministic_precheck(answer_dict)
    if precheck_errors:
        print(f"  [3/4] Pre-check failed — skipping LLM judge:")
        for err in precheck_errors:
            print(f"    - {err}")
        return {
            "dataset": name,
            "query": query,
            "status": "fail",
            "aggregate_score": 0.0,
            "precheck_errors": precheck_errors,
            "criteria": [],
            "raw_answer_truncated": raw_answer[:500] if raw_answer else None,
        }

    # 6. LLM judge scoring
    model_under_test = container.llm_provider.model_name if container.llm_provider else "unknown"
    print(f"  [4/4] Judging with {judge.model_name}...")

    judge_result = await judge.score(
        answer=answer_dict,
        expected=expected,
        dataset_name=name,
        model_under_test=model_under_test,
    )

    status = "pass" if judge_result.aggregate_score >= PASS_THRESHOLD else "fail"
    print(f"  Result: {status.upper()} (score: {judge_result.aggregate_score:.2f})")
    for c in judge_result.criteria:
        indicator = "✓" if c.score >= PASS_THRESHOLD else "✗"
        print(f"    {indicator} {c.name}: {c.score:.2f} — {c.explanation[:80]}")

    return {
        "dataset": name,
        "query": query,
        "status": status,
        "aggregate_score": judge_result.aggregate_score,
        "model_under_test": judge_result.model_under_test,
        "judge_model": judge_result.judge_model,
        "criteria": [c.model_dump() for c in judge_result.criteria],
        "raw_answer_truncated": raw_answer[:500] if raw_answer else None,
    }


async def main():
    args = _parse_args(sys.argv[1:])

    if args.get("no_reflection"):
        from repi.core.config import settings as _s
        _s.ENABLE_REFLECTION = False
        print("  [config] reflection disabled (--no-reflection)")

    dataset_filter = args.get("dataset_filter")
    container = get_container()
    await container.init_db()

    judge = _create_judge(args)
    print(f"  [config] judge model: {judge.model_name}")

    all_results = []

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
            result = await run_dataset(container, dataset, judge)
            all_results.append(result)
        except Exception as e:
            tb = traceback.format_exc()
            print(f"\n  ERROR in {dataset['name']}: {e}")
            print(tb)
            all_results.append({
                "dataset": dataset["name"],
                "status": "error",
                "error": str(e),
                "traceback": tb,
                "aggregate_score": 0.0,
                "criteria": [],
            })

    # Summary
    print(f"\n{'='*60}")
    print("  SUMMARY")
    print(f"{'='*60}")
    passed = sum(1 for r in all_results if r["status"] == "pass")
    failed = sum(1 for r in all_results if r["status"] == "fail")
    errored = sum(1 for r in all_results if r["status"] == "error")
    avg_score = (
        sum(r.get("aggregate_score", 0) for r in all_results) / len(all_results)
        if all_results else 0
    )
    print(f"  PASS: {passed}  FAIL: {failed}  ERROR: {errored}  Avg score: {avg_score:.2f}  Threshold: {PASS_THRESHOLD}")

    for r in all_results:
        score_str = f"{r.get('aggregate_score', 0):.2f}"
        print(f"    {r['status'].upper():5s}  {score_str}  {r['dataset']}")

    results_path = ROOT / "bug.json"
    with open(results_path, "w") as f:
        json.dump({
            "pass_threshold": PASS_THRESHOLD,
            "summary": {
                "passed": passed,
                "failed": failed,
                "errored": errored,
                "average_score": round(avg_score, 3),
            },
            "results": all_results,
        }, f, indent=2)
    print(f"\n  Results written to: {results_path}")

    return 0 if (failed == 0 and errored == 0) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
