"""
Multi-model eval orchestrator — runs the eval suite across a list of models
and prints a comparison table.

Usage:
    uv run python eval/run_multi_model.py --judge-provider gemini
    uv run python eval/run_multi_model.py --mock
    uv run python eval/run_multi_model.py --models models.json --judge-provider gemini
"""
from __future__ import annotations
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent

DEFAULT_MODELS = [
    {"provider": "openrouter", "model": "mistralai/mistral-large-latest"},
    {"provider": "openrouter", "model": "anthropic/claude-sonnet-4-20250514"},
    {"provider": "openrouter", "model": "openai/gpt-4o"},
]

MOCK_RESULTS = {
    "summary": {"passed": 3, "failed": 1, "errored": 0, "average_score": 0.78},
    "results": [
        {"dataset": "dataset_1_cascading_inventory_migration", "status": "pass",
         "aggregate_score": 0.85, "stats": {"iterations_used": 6}},
        {"dataset": "dataset_2_insufficient_logging", "status": "fail",
         "aggregate_score": 0.55, "stats": {"iterations_used": 8}},
        {"dataset": "dataset_3_jwt_key_rotation_noise", "status": "pass",
         "aggregate_score": 0.90, "stats": {"iterations_used": 4}},
        {"dataset": "dataset_4_discord_gateway_cascade", "status": "pass",
         "aggregate_score": 0.82, "stats": {"iterations_used": 7}},
    ],
}


def _parse_args(argv: list[str]) -> dict:
    args: dict = {}
    i = 0
    while i < len(argv):
        if argv[i] == "--mock":
            args["mock"] = True
        elif argv[i] == "--models" and i + 1 < len(argv):
            args["models_path"] = argv[i + 1]
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
        elif argv[i] == "--api-key" and i + 1 < len(argv):
            args["api_key"] = argv[i + 1]
            i += 1
        i += 1
    return args


def _load_models(args: dict) -> list[dict]:
    path = args.get("models_path")
    if path:
        return json.loads(Path(path).read_text())
    return DEFAULT_MODELS


def _short_name(model_id: str) -> str:
    return model_id.rsplit("/", 1)[-1][:28]


def _run_eval(model_cfg: dict, args: dict, out_path: Path) -> dict | None:
    cmd = [
        sys.executable, str(ROOT / "eval" / "run_evals.py"),
        "--provider", model_cfg["provider"],
        "--model", model_cfg["model"],
        "--out", str(out_path),
    ]
    if args.get("api_key"):
        cmd += ["--api-key", args["api_key"]]
    if args.get("judge_provider"):
        cmd += ["--judge-provider", args["judge_provider"]]
    if args.get("judge_model"):
        cmd += ["--judge-model", args["judge_model"]]
    if args.get("judge_api_key"):
        cmd += ["--judge-api-key", args["judge_api_key"]]

    print(f"\n  Running: {' '.join(cmd[:6])}...")
    result = subprocess.run(cmd, capture_output=False)
    if result.returncode != 0:
        print(f"  eval returned exit code {result.returncode}")

    if out_path.exists():
        return json.loads(out_path.read_text())
    return None


def _print_table(all_results: dict[str, dict]):
    datasets = set()
    for res in all_results.values():
        for r in res.get("results", []):
            datasets.add(r["dataset"])
    datasets_sorted = sorted(datasets)
    short_ds = [d.replace("dataset_", "D").split("_")[0] for d in datasets_sorted]

    header = f"  {'Model':<30s}"
    for sd in short_ds:
        header += f" | {sd:>6s}"
    header += f" | {'Avg':>6s} | {'Iters':>5s}"
    print(f"\n{'='*len(header)}")
    print(header)
    print(f"  {'-'*30}" + "".join(f"-+-{'-'*6}" for _ in short_ds) + f"-+-{'-'*6}-+-{'-'*5}")

    for model_id, res in all_results.items():
        name = _short_name(model_id)
        row = f"  {name:<30s}"
        scores = {}
        total_iters = 0
        for r in res.get("results", []):
            scores[r["dataset"]] = r.get("aggregate_score", 0.0)
            total_iters += (r.get("stats") or {}).get("iterations_used", 0)

        for ds in datasets_sorted:
            s = scores.get(ds, 0.0)
            row += f" | {s:>6.2f}"

        avg = res.get("summary", {}).get("average_score", 0.0)
        row += f" | {avg:>6.2f} | {total_iters:>5d}"
        print(row)

    print(f"{'='*len(header)}")


def main():
    args = _parse_args(sys.argv[1:])
    models = _load_models(args)
    is_mock = args.get("mock", False)

    if not is_mock and not args.get("judge_provider"):
        print("  ERROR: --judge-provider required (or use --mock for dry run)")
        return 1

    results_dir = ROOT / "eval" / "results"
    results_dir.mkdir(parents=True, exist_ok=True)

    all_results: dict[str, dict] = {}

    for model_cfg in models:
        model_id = model_cfg["model"]
        safe_name = model_id.replace("/", "_")
        out_path = results_dir / f"{safe_name}.json"

        if is_mock:
            print(f"\n  [mock] {model_id}")
            all_results[model_id] = MOCK_RESULTS
        else:
            res = _run_eval(model_cfg, args, out_path)
            if res:
                all_results[model_id] = res
            else:
                print(f"  WARNING: no results for {model_id}")

    if all_results:
        _print_table(all_results)

    return 0


if __name__ == "__main__":
    sys.exit(main())
