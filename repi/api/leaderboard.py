from fastapi import APIRouter
from repi.core.container import get_container

router = APIRouter(prefix="/leaderboard")


@router.get("")
async def get_leaderboard():
    container = get_container()
    if not container.pool:
        return {"rows": [], "error": "db pool not initialised"}

    async with container.pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, run_id, provider, model, dataset,
                   aggregate_score, status, judge_provider, judge_model,
                   criteria, stats, embedding_backend, created_at
            FROM leaderboard
            ORDER BY created_at DESC
            """
        )

    return {
        "rows": [
            {
                "id": str(r["id"]),
                "run_id": str(r["run_id"]),
                "provider": r["provider"],
                "model": r["model"],
                "dataset": r["dataset"],
                "aggregate_score": float(r["aggregate_score"]),
                "status": r["status"],
                "judge_provider": r["judge_provider"],
                "judge_model": r["judge_model"],
                "embedding_backend": r["embedding_backend"],
                "created_at": r["created_at"].isoformat(),
            }
            for r in rows
        ]
    }


LEADERBOARD_MODEL_LIMIT = 5


@router.get("/summary")
async def get_leaderboard_summary():
    """One row per model, top 5 by score. Previously this was
    DISTINCT ON (model, dataset), which produced a row per (model x dataset)
    pair and made a single model with several datasets flood the table with
    duplicate-looking rows.

    The average is taken over the model's *best* score per dataset (not its
    single most recent run, and not a raw average over every historical
    attempt): a model that got unlucky on one early run shouldn't have that
    drag its score down forever, and a model whose latest run only touched
    one of several datasets shouldn't get scored on that single data point.
    """
    container = get_container()
    if not container.pool:
        return {"models": [], "error": "db pool not initialised"}

    async with container.pool.acquire() as conn:
        rows = await conn.fetch(
            """
            WITH best_per_dataset AS (
                SELECT DISTINCT ON (model, dataset)
                       model, provider, dataset, aggregate_score,
                       judge_model, embedding_backend, created_at
                FROM leaderboard
                WHERE status NOT IN ('error', 'provider_error')
                ORDER BY model, dataset, aggregate_score DESC
            )
            SELECT model,
                   MAX(provider) AS provider,
                   AVG(aggregate_score) AS aggregate_score,
                   MAX(judge_model) AS judge_model,
                   MAX(embedding_backend) AS embedding_backend,
                   MAX(created_at) AS created_at
            FROM best_per_dataset
            GROUP BY model
            ORDER BY aggregate_score DESC
            LIMIT $1
            """,
            LEADERBOARD_MODEL_LIMIT,
        )

    return {
        "models": [
            {
                "model": r["model"],
                "provider": r["provider"],
                "aggregate_score": float(r["aggregate_score"]),
                "judge_model": r["judge_model"],
                "embedding_backend": r["embedding_backend"],
                "created_at": r["created_at"].isoformat(),
            }
            for r in rows
        ]
    }


@router.get("/retrieval")
async def get_retrieval_leaderboard():
    """RAGAS retrieval scores — one row per dataset, seeded from
    eval/ragas_results.json via `make seed-ragas` (see eval/seed_ragas.py)."""
    container = get_container()
    if not container.pool:
        return {"datasets": [], "error": "db pool not initialised"}

    async with container.pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT dataset, model, avg_service_recall, avg_keyword_recall,
                   embedding_backend, created_at
            FROM ragas
            WHERE category = 'retrieval'
            ORDER BY dataset
            """
        )

    return {
        "datasets": [
            {
                "dataset": r["dataset"],
                "model": r["model"],
                "avg_service_recall": float(r["avg_service_recall"]) if r["avg_service_recall"] is not None else None,
                "avg_keyword_recall": float(r["avg_keyword_recall"]) if r["avg_keyword_recall"] is not None else None,
                "embedding_backend": r["embedding_backend"],
                "created_at": r["created_at"].isoformat(),
            }
            for r in rows
        ]
    }
