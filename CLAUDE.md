# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**repi** is a Python log-investigation engine. It ingests log files into PostgreSQL (pgvector), retrieves relevant log clusters using hybrid search (BM25 + dense vectors with RRF), and runs a ReAct loop where an LLM autonomously investigates root causes using tool calls.

Two user-facing surfaces ship in the same package:

- **HTTP API** (`repi/api/`, FastAPI) — primary surface. Endpoints: `/ingest`, `/investigate`, `/investigations/*`, `/watchers`, `/services`, `/config`. Drives the web UI.
- **CLI** (`repi/cli.py`, Typer) — lifecycle commands only: `repi init`, `repi serve`, `repi ui`, `repi stop`. The CLI does **not** itself perform ingestion or investigation; those go through the API (or are invoked programmatically). Issue #29 tracks adding CLI-first investigate/sessions/watch commands; until then, use the API or web UI.
- **Worker** (`repi/worker.py`) — background process that polls `watcher_configs` and ingests new log bytes from registered file paths.

The `repi/` directory is the active codebase. Legacy folders under `lograg/`, `src/app/`, and `scripts/` are deleted/obsolete.

## Commands

This project uses [`uv`](https://docs.astral.sh/uv/), not Poetry.

```bash
# Install dependencies
uv sync

# First-time setup: brings up docker stack, prompts provider/key, writes .repi/config.json, applies schema
uv run repi init --with-docker

# Start the API (terminal 1) and web UI (terminal 2)
uv run repi serve
uv run repi ui

# Tear down the docker stack when done
uv run repi stop

# Apply DB schema manually (rarely needed — `repi init` runs it)
make migrate   # runs psql against db/schema.sql

# Ingest a log file (via HTTP API)
curl -X POST -F "service=my-svc" -F "file=@/path/to/app.log" http://localhost:8000/ingest

# Run an investigation (via HTTP API)
curl -X POST http://localhost:8000/investigate \
  -H "Content-Type: application/json" \
  -d '{"query": "why did checkout fail last friday night"}'

# Background worker for continuous ingestion
uv run python -m repi.worker

# Run all tests
uv run pytest tests/ -v

# Run a single test file
uv run pytest tests/investigation/test_react_loop.py -v

# Run the eval harness (datasets 1-3, grades against expected.json)
uv run python eval/run_evals.py
```

## Architecture

```
repi/
├── cli.py                  # Typer app — init, serve, ui, stop (lifecycle only)
├── worker.py               # Background file watcher — polls watcher_configs, ingests new bytes
├── api/
│   ├── __init__.py         # FastAPI app, /services endpoint, router wiring
│   ├── ingest.py           # POST /ingest
│   ├── investigate.py      # POST /investigate, /investigations/{id}/clarify, GET stream, list, detail
│   ├── watchers.py         # /watchers CRUD + /watchers/{id}/status
│   └── config.py           # GET/PUT /config — reads/writes .repi/config.json
├── core/
│   ├── config.py           # pydantic-settings (Settings class — reads .env + .repi/config.json)
│   ├── container.py        # DI container — initializes db pool, cache, llm, retrieval
│   ├── cache.py            # Redis caching (degrades gracefully if unavailable)
│   └── dates.py            # Date/time helpers
├── ingestion/
│   ├── log_parser.py       # Parse timestamps, levels, messages from raw log lines
│   ├── log_chunker.py      # Cluster logs by signature + 30s time window
│   └── log_ingestor.py     # Orchestrates parsing → chunking → embedding → upsert
├── retrieval/
│   ├── pgvector_store.py   # Vector DB via HNSW index (all-MiniLM-L6-v2, 384 dims)
│   ├── pg_fts_retriever.py # Full-text search using PostgreSQL GIN index
│   ├── rrf.py              # Reciprocal Rank Fusion combining vector + FTS rankings
│   ├── query_expander.py   # LLM-generated alternative query phrasings
│   ├── filter_builder.py   # Converts RetrievalFilters → SQL WHERE clauses
│   └── heuristics.py       # Progressive time-window expansion, log clustering
├── investigation/
│   ├── react_loop.py       # ReAct loop (thought → action → observation cycles)
│   ├── tools.py            # Tool implementations: search_logs, get_timeline, scan_window, get_service_summary
│   ├── schema.py           # InvestigationAnswer pydantic models + validate_answer()
│   ├── sweep.py            # auto_sweep — pre-loop log discovery
│   └── store.py            # Persist investigation steps and evidence chunks
├── llm/
│   ├── provider.py         # LLMProvider protocol + Message dataclass
│   ├── factory.py          # Creates provider from LLM_PROVIDER env var
│   └── adapters.py         # OpenAI, Anthropic, Mistral, Gemini, Ollama implementations
├── intent/
│   └── resolver.py         # Resolves natural-language query → service / time / level + clarification
└── models/
    ├── schema.py           # SQLModel tables: LogChunk, Investigation, InvestigationStep,
    │                       #                  InvestigationChunk, WatcherConfig, WatcherOffset
    ├── domain.py           # SearchResult pydantic model
    └── filters.py          # RetrievalFilters dataclass
```

## Key Data Flow

**Ingestion**: `log_parser` → `log_chunker` (groups by signature + 30s window) → SentenceTransformers embedding → upsert into `log_chunks` table with HNSW vector index.

**Investigation**: `POST /investigate` → `intent/resolver` extracts filters (or returns a clarification question) → hybrid search (pgvector HNSW + PostgreSQL FTS) → RRF fusion → results fed to LLM → ReAct loop with tool calls → `submit_answer`. Stream progress via `GET /investigations/{id}/stream`.

**ReAct loop** (`react_loop.py`): LLM returns JSON with `thought` + either `action`/`tool_input` or `final_answer`. Tools (`search_logs`, `get_timeline`, `scan_window`, `get_service_summary`) return structured observations. Max 10 iterations, 2 retries per step with 5s backoff. Steps and evidence persisted in the DB for audit. The final answer is validated by `validate_answer()` in `investigation/schema.py`.

**Worker**: `repi.worker` polls `watcher_configs` every `WATCHER_CONFIG_REFRESH_SECS` (default 30s) and uses `watchfiles` to detect new bytes on registered paths, ingesting incremental tails from the last stored offset.

## Configuration

repi reads configuration from three places, with precedence shell env > `.repi/config.json` > defaults in `core/config.py`. `.repi/config.json` is the canonical file — created by `repi init`, mutated by the web UI Config page (`PUT /config`), and gitignored.

Required:
- `DATABASE_URL` — PostgreSQL asyncpg URL (default: `postgresql+asyncpg://lograg_user:password_here@localhost:5432/lograg`)
- `LLM_PROVIDER` — `openai` | `anthropic` | `mistral` | `gemini` | `ollama` (default: `openai`)
- Provider API key — `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `MISTRAL_API_KEY`, `GEMINI_API_KEY`, or `LLM_API_KEY`

Optional:
- `REPI_ENV` — `production` (default) | `development`. Development enables verbose logs + `--reload`.
- `REDIS_URL` — Redis (default: `redis://localhost:6379`); set `ENABLE_REDIS_CACHE=false` to disable.
- `LLM_MODEL` — Override default model per provider.
- `TIME_WINDOW_INITIAL_MINUTES` — First search window (default: `10`).
- `TIME_WINDOW_EXPANSIONS` — Progressive expansion windows in minutes (default: `"60,360,1440"`).
- `UI_PORT` — Web UI port (default: `3000`).
- `WATCHER_CONFIG_REFRESH_SECS` — Worker config poll interval (default: `30`).
- `OLLAMA_BASE_URL` — Ollama endpoint (default: `http://localhost:11434`).

## Database Schema

Schema file: `db/schema.sql` (applied via `make migrate` or automatically by `repi init`).

- `log_chunks` — ingested log entries; `embedding vector(384)` with HNSW index; GIN index for FTS
- `investigations` — investigation sessions (query, status, answer, step count)
- `investigation_steps` — individual ReAct steps (thought, action JSONB, observation JSONB)
- `investigation_chunks` — evidence collected per investigation
- `watcher_configs` — registered file paths for the worker
- `watcher_offsets` — last-read byte offset per watcher

## Testing Notes

Tests use `pytest-asyncio`. `tests/investigation/conftest.py` provides shared async fixtures. Tests mock LLM providers and database — integration tests against a live DB are not currently configured.

The eval harness (`eval/run_evals.py`) seeds three scripted datasets and grades the LLM's investigation against `expected.json`; bugs are written to `bug.json` at the repo root.

Default LLM model: Mistral `mistral-large-latest`.
