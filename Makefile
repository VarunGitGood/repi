.PHONY: serve ui migrate reset-investigations

-include .env
export

# DATABASE_URL comes from .env when present, otherwise we extract it from
# .repi/config.json (the canonical source the app reads). Final fallback is
# the localhost class default so `make migrate` works on a fresh checkout.
ifeq ($(DATABASE_URL),)
DATABASE_URL := $(shell python3 -c "import json,sys,pathlib; p=pathlib.Path('.repi/config.json'); print(json.loads(p.read_text()).get('DATABASE_URL','')) if p.exists() else print('')" 2>/dev/null)
endif
ifeq ($(DATABASE_URL),)
DATABASE_URL := postgresql+asyncpg://repi_user:password_here@localhost:5432/repi
endif

# Strip the +asyncpg driver prefix so psql can parse the URL
PSQL_URL := $(shell echo "$(DATABASE_URL)" | sed 's|postgresql+asyncpg://|postgresql://|')

# Start the FastAPI backend (terminal 1).
serve:
	uv run repi serve

# Start the Next.js web UI (terminal 2).
ui:
	uv run repi ui

# Apply DB schema manually. `repi init` and `repi serve` run this automatically.
migrate:
	psql $(PSQL_URL) -f db/schema.sql

# Wipe investigation history when older rows are out of step with the schema.
# Cascades through investigation_steps and investigation_chunks via FK. Leaves
# log_chunks, watchers, and leaderboard alone.
reset-investigations:
	psql $(PSQL_URL) -c "TRUNCATE investigations CASCADE;"
