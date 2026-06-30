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


@router.get("/summary")
async def get_leaderboard_summary():
    """Best score per model per dataset — the comparison view."""
    container = get_container()
    if not container.pool:
        return {"models": [], "error": "db pool not initialised"}

    async with container.pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT DISTINCT ON (model, dataset)
                   model, provider, dataset, aggregate_score, status,
                   judge_model, embedding_backend, created_at
            FROM leaderboard
            WHERE status NOT IN ('error', 'provider_error')
            ORDER BY model, dataset, aggregate_score DESC
            """
        )

    return {
        "models": [
            {
                "model": r["model"],
                "provider": r["provider"],
                "dataset": r["dataset"],
                "aggregate_score": float(r["aggregate_score"]),
                "status": r["status"],
                "judge_model": r["judge_model"],
                "embedding_backend": r["embedding_backend"],
                "created_at": r["created_at"].isoformat(),
            }
            for r in rows
        ]
    }
