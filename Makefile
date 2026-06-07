.PHONY: migrate run query-test reset-investigations

-include .env
export

# DATABASE_URL comes from .env when present, otherwise we extract it from
# .repi/config.json (the canonical source the app reads). Final fallback is
# the localhost class default so `make migrate` works on a fresh checkout.
ifeq ($(DATABASE_URL),)
DATABASE_URL := $(shell python3 -c "import json,sys,pathlib; p=pathlib.Path('.repi/config.json'); print(json.loads(p.read_text()).get('DATABASE_URL','')) if p.exists() else print('')" 2>/dev/null)
endif
ifeq ($(DATABASE_URL),)
DATABASE_URL := postgresql+asyncpg://lograg_user:password_here@localhost:5432/lograg
endif

# Strip the +asyncpg driver prefix so psql can parse the URL
PSQL_URL := $(shell echo "$(DATABASE_URL)" | sed 's|postgresql+asyncpg://|postgresql://|')

# Runs automatically on `make serve`; only needed to apply schema outside the app.
migrate:
	psql $(PSQL_URL) -f db/schema.sql

# One-shot wipe of investigation history when older rows lack newer fields
# (stats, kind, compile_source). Cascades through investigation_steps and
# investigation_chunks via FK. Leaves log_chunks, watcher_*, leaderboard alone.
reset-investigations:
	psql $(PSQL_URL) -c "TRUNCATE investigations CASCADE;"

serve:
	uv run uvicorn repi.api:app --host 0.0.0.0 --port 8000 --reload

test-api:
	@echo "Testing API health..."
	curl -s http://localhost:8000/services | json_pp || echo "API not running"

ingest-test:
	@echo "Ingesting sample logs..."
	curl -X POST -F "service=auth-service" -F "file=@tests/data/sample_logs.txt" http://localhost:8000/ingest
