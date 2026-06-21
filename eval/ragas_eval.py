"""
RAGAS retrieval evaluation — measures retrieval quality in isolation.

Runs the RRF retrieval pipeline (pgvector + FTS) against purpose-built
datasets and scores with RAGAS metrics (context precision, context recall)
plus custom retrieval metrics (service recall, keyword recall).

Usage:
    uv run python eval/ragas_eval.py
    uv run python eval/ragas_eval.py --dataset ragas_cross_service
    uv run python eval/ragas_eval.py --out eval/ragas_results.json
"""
from __future__ import annotations

# ── langchain-community compat shim ──────────────────────────────────────────
# ragas imports `langchain_community.chat_models.vertexai.ChatVertexAI` which
# was removed in langchain-community 0.4.x. Patch it from the standalone
# package before ragas touches it.
import sys
import types

try:
    from langchain_google_vertexai import ChatVertexAI

    mod = types.ModuleType("langchain_community.chat_models.vertexai")
    mod.ChatVertexAI = ChatVertexAI
    sys.modules["langchain_community.chat_models.vertexai"] = mod
except ImportError:
    pass
# ─────────────────────────────────────────────────────────────────────────────

import asyncio
import importlib
import json
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from repi.core.container import get_container
from repi.models.filters import RetrievalFilters

# ── Dataset registry ────────────────────────────────────────────────────────

DATASETS = [
    {
        "name": "ragas_cross_service",
        "seed_module": "eval.ragas_datasets.ragas_cross_service.seed",
        "ground_truth_path": ROOT / "eval/ragas_datasets/ragas_cross_service/ground_truth.json",
    },
    {
        "name": "ragas_temporal_precision",
        "seed_module": "eval.ragas_datasets.ragas_temporal_precision.seed",
        "ground_truth_path": ROOT / "eval/ragas_datasets/ragas_temporal_precision/ground_truth.json",
    },
    {
        "name": "ragas_noise_resilience",
        "seed_module": "eval.ragas_datasets.ragas_noise_resilience.seed",
        "ground_truth_path": ROOT / "eval/ragas_datasets/ragas_noise_resilience/ground_truth.json",
    },
    {
        "name": "ragas_loghub_real",
        "seed_module": "eval.ragas_datasets.ragas_loghub_real.seed",
        "ground_truth_path": ROOT / "eval/ragas_datasets/ragas_loghub_real/ground_truth.json",
    },
]


# ── CLI arg parsing ──────────────────────────────────────────────────────────

def _parse_args(argv: list[str]) -> dict:
    args: dict = {}
    i = 0
    while i < len(argv):
        if argv[i] == "--dataset" and i + 1 < len(argv):
            args["dataset_filter"] = argv[i + 1]
            i += 1
        elif argv[i] == "--out" and i + 1 < len(argv):
            args["out_path"] = argv[i + 1]
            i += 1
        elif argv[i] == "--top-k" and i + 1 < len(argv):
            args["top_k"] = int(argv[i + 1])
            i += 1
        elif argv[i] == "--evaluator-provider" and i + 1 < len(argv):
            args["evaluator_provider"] = argv[i + 1]
            i += 1
        i += 1
    return args


# ── Retrieval runner ─────────────────────────────────────────────────────────

async def retrieve_contexts(
    container,
    question: str,
    filters_dict: dict | None = None,
    top_k: int = 10,
) -> list[dict]:
    """Run the RRF retrieval pipeline for a single question and return chunks."""
    async with container.get_session() as session:
        rrf = container.get_retrieval_service(session)

        filters = None
        if filters_dict:
            from repi.core.dates import DateHandler
            filters = RetrievalFilters(
                time_from=DateHandler.parse_iso(filters_dict.get("time_from")),
                time_to=DateHandler.parse_iso(filters_dict.get("time_to")),
                source_service=filters_dict.get("service"),
            )

        results = await rrf.search(query=question, top_k=top_k, filters=filters)

        chunk_ids = [cid for cid, _ in results]
        chunks_data = await rrf.vector_store.get_chunks_by_ids(chunk_ids)

        retrieved = []
        for chunk_id, score in results:
            data = chunks_data.get(chunk_id, {})
            retrieved.append({
                "chunk_id": chunk_id,
                "text": data.get("text", ""),
                "service": data.get("source_service", ""),
                "score": float(score),
            })

    return retrieved


# ── RAGAS evaluation ─────────────────────────────────────────────────────────

def _make_ragas_llm(provider: str | None = None):
    """Create a RAGAS-compatible LLM.

    Tries providers in order: explicit override > Gemini > Mistral.
    Uses the OpenAI-compatible endpoint for both (Gemini has one,
    Mistral's API is natively OpenAI-compatible).
    """
    from openai import OpenAI
    from ragas.llms import llm_factory
    from repi.core.config import settings

    providers = []
    if provider:
        providers = [provider]
    else:
        providers = ["mistral", "gemini"]

    for p in providers:
        if p == "gemini":
            api_key = settings.GEMINI_API_KEY or settings.GOOGLE_API_KEY
            if not api_key:
                continue
            client = OpenAI(
                api_key=api_key,
                base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
            )
            print(f"  [config] RAGAS evaluator: Gemini (gemini-2.0-flash)")
            return llm_factory(model="gemini-2.0-flash", provider="openai", client=client)

        elif p == "mistral":
            api_key = settings.MISTRAL_API_KEY
            if not api_key:
                continue
            client = OpenAI(
                api_key=api_key,
                base_url="https://api.mistral.ai/v1",
            )
            print(f"  [config] RAGAS evaluator: Mistral (mistral-small-2506)")
            return llm_factory(model="mistral-small-2506", provider="openai", client=client)

    raise RuntimeError(
        "No evaluator LLM available. Configure GEMINI_API_KEY or MISTRAL_API_KEY in .repi/config.json"
    )


def _make_ragas_embeddings(provider: str | None = None):
    """Create RAGAS-compatible embeddings for answer_relevancy."""
    from langchain_mistralai import MistralAIEmbeddings
    from repi.core.config import settings
    import warnings
    warnings.filterwarnings("ignore", message=".*LangchainEmbeddingsWrapper.*deprecated.*")

    api_key = settings.MISTRAL_API_KEY
    if not api_key:
        return None

    from ragas.embeddings import LangchainEmbeddingsWrapper
    emb = MistralAIEmbeddings(model="mistral-embed", api_key=api_key)
    print(f"  [config] RAGAS embeddings: Mistral (mistral-embed)")
    return LangchainEmbeddingsWrapper(emb)


def run_ragas_evaluation(eval_samples: list[dict], evaluator_provider: str | None = None) -> dict:
    """Run RAGAS metrics on the collected samples."""
    import warnings
    import signal
    import re
    warnings.filterwarnings("ignore", message=".*deprecated.*ragas.metrics.*")

    from ragas import evaluate
    from ragas.metrics._context_precision import ContextPrecision
    from ragas.metrics._context_recall import ContextRecall
    from ragas.metrics._answer_relevance import AnswerRelevancy
    from ragas.run_config import RunConfig
    from datasets import Dataset

    llm = _make_ragas_llm(provider=evaluator_provider)
    embeddings = _make_ragas_embeddings(provider=evaluator_provider)

    metrics = [
        ContextPrecision(),
        ContextRecall(),
        AnswerRelevancy(),
    ]

    data = {
        "question": [s["question"] for s in eval_samples],
        "contexts": [s["retrieved_contexts"] for s in eval_samples],
        "answer": [s.get("ground_truth_answer", "") for s in eval_samples],
        "ground_truth": [s.get("ground_truth_answer", "") for s in eval_samples],
    }

    dataset = Dataset.from_dict(data)

    run_config = RunConfig(
        timeout=300,
        max_retries=5,
        max_wait=120,
        max_workers=5,
    )

    TIMEOUT_SECS = 7200  # 2 hours

    def _timeout_handler(signum, frame):
        raise TimeoutError(f"RAGAS evaluate timed out after {TIMEOUT_SECS}s")

    old_handler = signal.signal(signal.SIGALRM, _timeout_handler)
    signal.alarm(TIMEOUT_SECS)
    try:
        eval_kwargs = dict(
            dataset=dataset,
            metrics=metrics,
            llm=llm,
            run_config=run_config,
            raise_exceptions=False,
            allow_nest_asyncio=True,
        )
        if embeddings:
            eval_kwargs["embeddings"] = embeddings
        result = evaluate(**eval_kwargs)
        signal.alarm(0)
    except TimeoutError:
        signal.alarm(0)
        print(f"  [warn] RAGAS evaluate timed out after {TIMEOUT_SECS}s", flush=True)
        return {"error": f"timed out after {TIMEOUT_SECS}s"}
    finally:
        signal.signal(signal.SIGALRM, old_handler)

    scores = {}
    result_str = str(result)
    for match in re.finditer(r"'(\w+)':\s*([\d.]+(?:e[+-]?\d+)?|nan)", result_str):
        metric_name = match.group(1)
        try:
            val = float(match.group(2))
            scores[metric_name] = round(val, 4)
        except ValueError:
            scores[metric_name] = match.group(2)

    return scores


# ── Dataset runner ───────────────────────────────────────────────────────────

async def run_dataset(container, dataset: dict, top_k: int = 10, evaluator_provider: str | None = None) -> dict:
    name = dataset["name"]
    gt = json.loads(dataset["ground_truth_path"].read_text())

    print(f"\n{'=' * 60}")
    print(f"  Dataset: {name}")
    print(f"{'=' * 60}")

    # 1. Seed
    print(f"  [1/3] Seeding...")
    seed_mod = importlib.import_module(dataset["seed_module"])
    await seed_mod.main()

    # 2. Init pool
    if not container.pool:
        await container.init_db()

    # 3. Retrieve for each question
    print(f"  [2/3] Retrieving ({len(gt['questions'])} questions, top_k={top_k})...")
    eval_samples = []
    retrieval_details = []

    for q_entry in gt["questions"]:
        question = q_entry["question"]
        filters_dict = q_entry.get("filters")

        retrieved = await retrieve_contexts(
            container, question, filters_dict, top_k=top_k
        )
        retrieved_texts = [c["text"] for c in retrieved]
        retrieved_services = [c["service"] for c in retrieved]

        # Check how many ground truth services are represented
        gt_services = set(q_entry.get("ground_truth_services", []))
        found_services = set(retrieved_services) & gt_services
        service_recall = len(found_services) / len(gt_services) if gt_services else 1.0

        # Check keyword coverage in retrieved texts
        gt_keywords = q_entry.get("ground_truth_keywords", [])
        all_text = " ".join(retrieved_texts).lower()
        keywords_found = [kw for kw in gt_keywords if kw.lower() in all_text]
        keyword_recall = len(keywords_found) / len(gt_keywords) if gt_keywords else 1.0

        gt_contexts = []
        for svc in q_entry.get("ground_truth_services", []):
            for c in retrieved:
                if c["service"] == svc:
                    gt_contexts.append(c["text"])

        if not gt_contexts:
            gt_contexts = retrieved_texts[:3] if retrieved_texts else [""]

        sample = {
            "question": question,
            "retrieved_contexts": retrieved_texts,
            "ground_truth_answer": q_entry["ground_truth_answer"],
            "ground_truth_contexts": gt_contexts,
        }
        eval_samples.append(sample)

        detail = {
            "question": question,
            "chunks_retrieved": len(retrieved),
            "services_retrieved": list(set(retrieved_services)),
            "service_recall": round(service_recall, 3),
            "keyword_recall": round(keyword_recall, 3),
            "keywords_found": keywords_found,
            "keywords_missed": [kw for kw in gt_keywords if kw.lower() not in all_text],
            "top_3_scores": [round(c["score"], 4) for c in retrieved[:3]],
        }
        retrieval_details.append(detail)

        print(f"    Q: \"{question}\"")
        print(f"       chunks={len(retrieved)}  service_recall={service_recall:.0%}  keyword_recall={keyword_recall:.0%}")

    # 4. Run RAGAS
    print(f"  [3/3] Running RAGAS metrics...", flush=True)
    scores = run_ragas_evaluation(eval_samples, evaluator_provider=evaluator_provider)

    status = "error" if "error" in scores else "completed"
    print(f"\n  RAGAS Scores:", flush=True)
    for metric_name, score_val in scores.items():
        if isinstance(score_val, (int, float)):
            print(f"    {metric_name:25s}  {score_val:.4f}", flush=True)
        else:
            print(f"    {metric_name:25s}  {score_val}", flush=True)

    print(f"\n  Retrieval Details:", flush=True)
    for d in retrieval_details:
        missed = d["keywords_missed"]
        missed_str = f" (missed: {', '.join(missed)})" if missed else ""
        print(f"    Q: \"{d['question']}\"", flush=True)
        print(f"       services={d['services_retrieved']}  keyword_recall={d['keyword_recall']:.0%}{missed_str}", flush=True)

    return {
        "dataset": name,
        "status": status,
        "ragas_scores": scores,
        "retrieval_details": retrieval_details,
    }


# ── Main ─────────────────────────────────────────────────────────────────────

async def main():
    args = _parse_args(sys.argv[1:])
    dataset_filter = args.get("dataset_filter")
    top_k = args.get("top_k", 10)
    evaluator_provider = args.get("evaluator_provider")

    container = get_container()
    await container.init_db()

    datasets_to_run = (
        [d for d in DATASETS if dataset_filter in d["name"]]
        if dataset_filter
        else DATASETS
    )
    if dataset_filter and not datasets_to_run:
        print(f"  [error] --dataset '{dataset_filter}' matched no datasets")
        return 1

    all_results = []
    for dataset in datasets_to_run:
        try:
            result = await run_dataset(container, dataset, top_k=top_k, evaluator_provider=evaluator_provider)
            all_results.append(result)
        except Exception as e:
            import traceback
            tb = traceback.format_exc()
            print(f"\n  ERROR in {dataset['name']}: {e}")
            print(tb)
            all_results.append({
                "dataset": dataset["name"],
                "status": "error",
                "error": str(e),
            })

    # Summary
    print(f"\n{'=' * 60}")
    print("  RAGAS EVALUATION SUMMARY")
    print(f"{'=' * 60}")

    for r in all_results:
        status = r.get("status", "unknown")
        print(f"\n  {r['dataset']}  [{status}]")
        if status == "completed":
            scores = r.get("ragas_scores", {})
            for metric_name, score_val in scores.items():
                if isinstance(score_val, (int, float)):
                    indicator = "+" if score_val >= 0.7 else "-"
                    print(f"    {indicator} {metric_name:25s}  {score_val:.4f}")
                else:
                    print(f"    ? {metric_name:25s}  {score_val}")

    out_path = args.get("out_path")
    if out_path:
        path_obj = Path(out_path)
        path_obj.parent.mkdir(parents=True, exist_ok=True)
        with open(path_obj, "w") as f:
            json.dump(all_results, f, indent=2)
        print(f"\n  Results written to: {path_obj}")

    if container.pool:
        await container.pool.close()

    return 0


if __name__ == "__main__":
    ret = asyncio.run(main())
    import os
    os._exit(ret or 0)
