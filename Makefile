.PHONY: migrate run query-test

-include .env
export

migrate:
	poetry run psql $(DATABASE_URL) -f db/migrations/001_init.sql

migrate-watchers:
	poetry run psql $(DATABASE_URL) -f db/migrations/002_watchers.sql

serve:
	poetry run uvicorn repi.api:app --host 0.0.0.0 --port 8000 --reload

test-api:
	@echo "Testing API health..."
	curl -s http://localhost:8000/services | json_pp || echo "API not running"

ingest-test:
	@echo "Ingesting sample logs..."
	curl -X POST -F "service=auth-service" -F "file=@tests/data/sample_logs.txt" http://localhost:8000/ingest
