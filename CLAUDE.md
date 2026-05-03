# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**repi** is a Python CLI tool for log ingestion and LLM-based investigation. It ingests log files into PostgreSQL (pgvector), retrieves relevant log clusters using hybrid search (BM25 + dense vectors with RRF), and runs a ReAct loop where an LLM autonomously investigates root causes using tool calls.

The `repi/` directory is the active codebase. Files under `lograg/`, `src/app/`, and `scripts/` are deleted/legacy.

## Commands

```bash
# Install dependencies
poetry install

# Apply DB schema
make migrate   # runs psql $DATABASE_URL -f db/migrations/001_init.sql

# Ingest a log file
poetry run repi ingest <service_name> <log_file_path>

# Run investigation
poetry run repi investigate "<natural language query>"

# Run all tests
poetry run pytest tests/ -v

# Run a single test file
poetry run pytest tests/test_tools.py -v

# Run async tests
poetry run pytest tests/investigation/ -v
```

## Architecture

```
repi/
├── cli.py                  # Entry point — typer app with ingest + investigate commands
├── core/
│   ├── config.py           # pydantic-settings (Settings class, reads .env)
│   ├── container.py        # Dependency injection — initializes db, cache, llm, retrieval
│   └── cache.py            # Redis caching (gracefully degrades if unavailable)
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
│   ├── tools.py            # Tool implementations: search_logs, get_timeline, find_co_occurring, get_service_summary
│   └── store.py            # Persist investigation steps and evidence chunks
├── llm/
│   ├── provider.py         # LLMProvider protocol + Message dataclass
│   ├── factory.py          # Creates provider from LLM_PROVIDER env var
│   └── adapters.py         # OpenAI, Anthropic, Mistral, Gemini, Ollama implementations
├── intent/
│   └── basic_parser.py     # Regex extraction of service, log_level, time_range from query
└── models/
    ├── schema.py           # SQLModel tables: LogChunk, Investigation, InvestigationStep, InvestigationChunk
    ├── domain.py           # SearchResult pydantic model
    └── filters.py          # RetrievalFilters dataclass
```

## Key Data Flow

**Ingestion**: `log_parser` → `log_chunker` (groups by signature + 30s window) → SentenceTransformers embedding → upsert into `log_chunks` table with HNSW vector index.

**Investigation**: intent parser extracts filters → hybrid search (pgvector HNSW + PostgreSQL FTS) → RRF fusion → results fed to LLM → ReAct loop with tool calls → `final_answer`.

**ReAct loop** (`react_loop.py`): LLM returns JSON with `thought` + either `action`/`tool_input` or `final_answer`. Tools return structured observations. Max 10 iterations, 2 retries per step with 5s backoff. Steps and evidence persisted in the DB for audit.

## Environment Variables

Required:
- `DATABASE_URL` — PostgreSQL asyncpg URL (default: `postgresql+asyncpg://postgres:postgres@localhost:5432/lograg`)
- `LLM_PROVIDER` — `openai` | `anthropic` | `mistral` | `gemini` | `ollama` (default: `openai`)
- Provider API key — `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `MISTRAL_API_KEY`, `GEMINI_API_KEY`, or `LLM_API_KEY`

Optional:
- `REDIS_URL` — Redis (default: `redis://localhost:6379`); set `ENABLE_REDIS_CACHE=false` to disable
- `LLM_MODEL` — Override default model per provider
- `TIME_WINDOW_INITIAL_MINUTES` — First search window (default: `10`)
- `TIME_WINDOW_EXPANSIONS` — Progressive expansion windows in minutes (default: `"60,360,1440"`)
- `OLLAMA_BASE_URL` — Ollama endpoint (default: `http://localhost:11434`)

## Database Schema

Migration file: `db/migrations/001_init.sql`

- `log_chunks` — ingested log entries; `embedding vector(384)` with HNSW index; GIN index for FTS
- `investigations` — investigation sessions (query, status, answer, step count)
- `investigation_steps` — individual ReAct steps (thought, action JSONB, observation JSONB)
- `investigation_chunks` — evidence collected per investigation

## Testing Notes

Tests use `pytest-asyncio`. The `tests/investigation/conftest.py` provides shared async fixtures. Tests mock LLM providers and database — integration tests against a live DB are not currently configured.

Default LLM models:  Mistral `mistral-large-latest`
