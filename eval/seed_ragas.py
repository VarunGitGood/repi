"""
Seed the `ragas` table from a RAGAS retrieval eval artifact (eval/ragas_results.json,
produced by eval/ragas_eval.py). Retrieval quality isn't currently written to the DB
by ragas_eval.py itself, so the demo leaderboard reads from this table instead of
the file directly.

Usage:
    uv run python eval/seed_ragas.py
    uv run python eval/seed_ragas.py --in eval/ragas_results.json
"""
from __future__ import annotations
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from repi.core.container import get_container

# eval/ragas_eval.py doesn't record which embedding backend or model it ran
# against in the output artifact — these mirror the project defaults (see
# repi/retrieval/pgvector_store.py and CLAUDE.md's "Default LLM model").
DEFAULT_EMBEDDING_BACKEND = "all-MiniLM-L6-v2"
DEFAULT_MODEL = "mistral-large-latest"


def _parse_args(argv: list[str]) -> dict:
    args = {"in_path": ROOT / "eval/ragas_results.json"}
    i = 0
    while i < len(argv):
        if argv[i] == "--in" and i + 1 < len(argv):
            args["in_path"] = Path(argv[i + 1])
            i += 2
        else:
            i += 1
    return args


async def main():
    args = _parse_args(sys.argv[1:])
    in_path: Path = args["in_path"]
    entries = json.loads(in_path.read_text())

    container = get_container()
    await container.init_db()
    if not container.pool:
        print("[seed_ragas] db pool not initialised — aborting")
        return

    async with container.pool.acquire() as conn:
        async with conn.transaction():
            for entry in entries:
                dataset = entry["dataset"]
                scores = entry.get("ragas_scores", {})
                # Idempotent re-seed: replace any prior rows for this dataset.
                await conn.execute("DELETE FROM ragas WHERE dataset = $1", dataset)
                await conn.execute(
                    """
                    INSERT INTO ragas (
                        dataset, category, status, model,
                        avg_service_recall, avg_keyword_recall,
                        embedding_backend, details
                    ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8::jsonb)
                    """,
                    dataset,
                    entry.get("category", "retrieval"),
                    entry.get("status", "unknown"),
                    DEFAULT_MODEL,
                    scores.get("avg_service_recall"),
                    scores.get("avg_keyword_recall"),
                    DEFAULT_EMBEDDING_BACKEND,
                    json.dumps(entry.get("retrieval_details", [])),
                )
                print(f"  [ragas] seeded {dataset} ({entry.get('category', 'retrieval')})")

    print(f"[seed_ragas] seeded {len(entries)} row(s) from {in_path}")


if __name__ == "__main__":
    asyncio.run(main())
