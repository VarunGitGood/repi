.PHONY: migrate run query-test

-include .env
export

# Strip the +asyncpg driver prefix so psql can parse the URL
PSQL_URL := $(shell echo "$(DATABASE_URL)" | sed 's|postgresql+asyncpg://|postgresql://|')

# Runs automatically on `make serve`; only needed to apply schema outside the app.
migrate:
	psql $(PSQL_URL) -f db/schema.sql

serve:
	uv run uvicorn repi.api:app --host 0.0.0.0 --port 8000 --reload

test-api:
	@echo "Testing API health..."
	curl -s http://localhost:8000/services | json_pp || echo "API not running"

ingest-test:
	@echo "Ingesting sample logs..."
	curl -X POST -F "service=auth-service" -F "file=@tests/data/sample_logs.txt" http://localhost:8000/ingest
