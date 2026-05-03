.PHONY: setup migrate run ingest-test query-test

-include .env
export

setup:
	poetry add sqlmodel pgvector asyncpg sentence-transformers fastapi uvicorn typer rich tqdm

migrate:
	poetry run psql $(DATABASE_URL) -f db/migrations/001_init.sql

migrate-watchers:
	poetry run psql $(DATABASE_URL) -f db/migrations/002_watchers.sql

serve:
	poetry run uvicorn repi.api:app --host 0.0.0.0 --port 8000 --reload

ingest-test:
	curl -X POST http://localhost:8000/api/v1/ingest \
	-H "Content-Type: application/json" \
	-d '{"source_service": "auth-service", "source_env": "production", "logs": "2026-04-28 00:44:00 [ERROR] Auth failure\n2026-04-28 00:45:00 [INFO] User login"}'

query-test:
	poetry run python -m src.app.cli query "ERROR in auth-service last 5 minutes"

eval:
	poetry run python -m evaluation.runner
