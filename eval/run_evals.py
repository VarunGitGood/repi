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
from uuid import UUID, uuid4

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from repi.core.container import get_container
from repi.llm.adapters import LLMBadRequestError, LLMError
from eval.judge import LLMJudge, PASS_THRESHOLD

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
        elif argv[i] == "--out" and i + 1 < len(argv):
            args["out_path"] = argv[i + 1]
            i += 1
        i += 1
    return args


def create_judge(args: dict, mut_provider_name: str) -> LLMJudge:
    """Create the judge LLM provider.

    Self-grading (judge provider == model-under-test provider) is disallowed
    unless `--judge-provider` is passed explicitly to opt in. The auto path
    prefers OpenAI → Anthropic → Gemini, picking the first provider whose
    API key is configured AND that differs from the MUT.
    """
    from repi.llm.adapters import (
        OpenAIProvider, AnthropicProvider, MistralProvider,
        GeminiProvider, OllamaProvider,
    )

    judge_provider_name = args.get("judge_provider")

    if judge_provider_name:
        # Explicit override — caller takes responsibility for any self-grading.
        api_key = args.get("judge_api_key", "")
        # If no --judge-api-key, look up the key for this provider from settings.
        if not api_key:
            from repi.core.config import settings as _s
            api_key = {
                "openai": _s.OPENAI_API_KEY,
                "anthropic": _s.ANTHROPIC_API_KEY,
                "mistral": _s.MISTRAL_API_KEY,
                "gemini": _s.GEMINI_API_KEY,
            }.get(judge_provider_name.lower(), "") or ""
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
        if judge_provider_name.lower() == mut_provider_name.lower():
            print(
                f"  [config] WARNING: --judge-provider matches MUT provider "
                f"({mut_provider_name}). Self-grading risk."
            )
        judge = LLMJudge(factory())
        judge.provider_name = judge_provider_name.lower()
        return judge

    # Auto-pick: find the first provider != MUT that has a key configured.
    from repi.core.config import settings
    mut = mut_provider_name.lower()
    preferences = [
        ("openai", settings.OPENAI_API_KEY, lambda k: OpenAIProvider(api_key=k, model="gpt-4o")),
        ("anthropic", settings.ANTHROPIC_API_KEY, lambda k: AnthropicProvider(api_key=k, model="claude-3-5-sonnet-20240620")),
        ("gemini", settings.GEMINI_API_KEY, lambda k: GeminiProvider(api_key=k, model="gemini-1.5-pro")),
        ("mistral", settings.MISTRAL_API_KEY, lambda k: MistralProvider(api_key=k, model="mistral-large-latest")),
    ]
    for name, key, factory in preferences:
        if name == mut:
            continue
        if key:
            print(f"  [config] judge provider auto-selected: {name} (MUT: {mut})")
            judge = LLMJudge(factory(key))
            judge.provider_name = name
            return judge

    # No alternative provider available — hard fail per Issue #49 contract.
    raise RuntimeError(
        f"Judge provider auto-selection failed: model-under-test is '{mut}' and no "
        "alternative provider key is configured. Configure a second provider key "
        "(OPENAI_API_KEY / ANTHROPIC_API_KEY / GEMINI_API_KEY in .repi/config.json) "
        "OR pass --judge-provider <name> --judge-api-key <key> explicitly to opt "
        "into self-grading."
    )

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

    # 4. Parse answer (always populated — the compiler guarantees a real answer).
    print(f"  [3/4] Parsing answer...")
    raw_answer = result.answer or "{}"
    try:
        answer_dict = json.loads(raw_answer)
    except json.JSONDecodeError:
        answer_dict = {}

    # 5. LLM judge scoring (no precheck gate — every answer reaches the judge).
    model_under_test = container.llm_provider.model_name if container.llm_provider else "unknown"
    print(f"  [4/4] Judging with {judge.model_name}...")

    judge_status: str | None = None
    try:
        judge_result = await judge.score(
            answer=answer_dict,
            expected=expected,
            dataset_name=name,
            model_under_test=model_under_test,
        )
    except LLMBadRequestError as e:
        print(f"  Judge provider error ({e.status_code}): {str(e)[:160]}")
        return _provider_error_result(name, query, result, raw_answer, e)
    except LLMError as e:
        print(f"  Judge LLM error: {e}")
        return _provider_error_result(name, query, result, raw_answer, e)

    # Distinguish a true judge_parse_error (parser retried and failed) from
    # a normal pass/fail outcome.
    parse_attempts = getattr(judge, "last_parse_attempts", 1)
    all_zero_after_retry = (
        parse_attempts >= 2
        and all(c.score == 0.0 for c in judge_result.criteria)
    )
    if all_zero_after_retry:
        judge_status = "judge_parse_error"

    status = judge_status or (
        "pass" if judge_result.aggregate_score >= PASS_THRESHOLD else "fail"
    )
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
        "stats": result.stats,
        "judge_parse_attempts": parse_attempts,
    }


def _provider_error_result(name: str, query: str, result, raw_answer: str, err: Exception) -> dict:
    return {
        "dataset": name,
        "query": query,
        "status": "provider_error",
        "aggregate_score": 0.0,
        "criteria": [],
        "raw_answer_truncated": raw_answer[:500] if raw_answer else None,
        "stats": getattr(result, "stats", {}) or {},
        "error": str(err)[:500],
    }


async def _write_leaderboard_row(
    container,
    *,
    run_id: UUID,
    result: dict,
    mut_provider: str,
    mut_model: str,
    judge_provider: str,
    judge_model: str,
    embedding_backend: str,
) -> None:
    """Insert one leaderboard row. Best-effort: any failure is logged and swallowed
    so the eval run is never blocked by persistence."""
    if not container.pool:
        print("  [leaderboard] skipped — db pool not initialised")
        return
    try:
        async with container.pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO leaderboard (
                    run_id, provider, model, dataset, aggregate_score,
                    status, judge_provider, judge_model, criteria, stats,
                    embedding_backend
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9::jsonb, $10::jsonb, $11)
                """,
                run_id,
                mut_provider,
                mut_model,
                result.get("dataset", ""),
                float(result.get("aggregate_score", 0.0) or 0.0),
                result.get("status", "unknown"),
                judge_provider,
                judge_model,
                json.dumps(result.get("criteria", []) or []),
                json.dumps(result.get("stats", {}) or {}),
                embedding_backend,
            )
    except Exception as e:
        # Never block the eval run on a persistence failure.
        print(f"  [leaderboard] insert failed for {result.get('dataset')}: {e}")


async def main():
    args = _parse_args(sys.argv[1:])

    if args.get("no_reflection"):
        from repi.core.config import settings as _s
        _s.ENABLE_REFLECTION = False
        print("  [config] reflection disabled (--no-reflection)")

    dataset_filter = args.get("dataset_filter")
    container = get_container()
    await container.init_db()

    # Look up the MUT provider before picking a judge so the auto-selector
    # can guarantee judge != MUT.
    from repi.core.config import settings as _settings
    mut_provider = _settings.LLM_PROVIDER

    judge = create_judge(args, mut_provider_name=mut_provider)
    print(f"  [config] judge model: {judge.model_name}")

    run_id = uuid4()
    judge_provider = getattr(judge, "provider_name", "unknown")
    mut_model = container.llm_provider.model_name if container.llm_provider else "unknown"
    embedding_backend = _settings.EMBEDDING_BACKEND
    print(f"  [run]    run_id: {run_id}")
    print(f"  [config] embedding_backend: {embedding_backend}")

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
            result = {
                "dataset": dataset["name"],
                "status": "error",
                "error": str(e),
                "traceback": tb,
                "aggregate_score": 0.0,
                "criteria": [],
            }
            all_results.append(result)

        # Best-effort persist. Even errored datasets get a row so the
        # leaderboard reflects the full run.
        await _write_leaderboard_row(
            container,
            run_id=run_id,
            result=result,
            mut_provider=mut_provider,
            mut_model=mut_model,
            judge_provider=judge_provider,
            judge_model=judge.model_name,
            embedding_backend=embedding_backend,
        )

    # Summary
    print(f"\n{'='*60}")
    print("  SUMMARY")
    print(f"{'='*60}")
    passed = sum(1 for r in all_results if r["status"] == "pass")
    failed = sum(1 for r in all_results if r["status"] == "fail")
    errored = sum(1 for r in all_results if r["status"] in ("error", "provider_error", "judge_parse_error"))
    avg_score = (
        sum(r.get("aggregate_score", 0) for r in all_results) / len(all_results)
        if all_results else 0
    )
    print(f"  PASS: {passed}  FAIL: {failed}  ERROR: {errored}  Avg score: {avg_score:.2f}  Threshold: {PASS_THRESHOLD}")

    for r in all_results:
        score_str = f"{r.get('aggregate_score', 0):.2f}"
        stats = r.get("stats") or {}
        bits = []
        if "iterations_used" in stats:
            bits.append(f"iter={stats['iterations_used']}")
        if "chunks_gathered" in stats:
            bits.append(f"chunks={stats['chunks_gathered']}")
        if "compile_source" in stats:
            bits.append(f"compile={stats['compile_source']}")
        if "judge_parse_attempts" in r:
            bits.append(f"judge_parses={r['judge_parse_attempts']}")
        suffix = (" [" + " ".join(bits) + "]") if bits else ""
        print(f"    {r['status'].upper():18s}  {score_str}  {r['dataset']}{suffix}")

    # Optional machine-readable output. No file is written by default —
    # bug.json was retired in Issue #49.
    out_path = args.get("out_path")
    if out_path:
        path_obj = Path(out_path)
        path_obj.parent.mkdir(parents=True, exist_ok=True)
        with open(path_obj, "w") as f:
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
        print(f"\n  Results written to: {path_obj}")

    return 0 if (failed == 0 and errored == 0) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
