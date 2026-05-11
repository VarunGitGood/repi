# repi

Log ingestion and LLM-based investigation engine. Ingests log files into PostgreSQL (pgvector), retrieves relevant log clusters via hybrid search (BM25 + dense vectors with RRF), and runs a ReAct loop where an LLM autonomously investigates root causes.

## Architecture

```
repi/
├── api/            # FastAPI — ingest, investigate, watchers, config endpoints
├── core/           # Settings (pydantic-settings), DI container, Redis cache
├── ingestion/      # Log parsing → signature clustering → embedding → upsert
├── retrieval/      # pgvector HNSW + PostgreSQL FTS, RRF fusion, query expansion
├── investigation/  # ReAct loop, tools (search_logs, get_timeline, scan_window), evidence store
├── llm/            # Provider protocol + adapters (OpenAI, Anthropic, Mistral, Gemini, Ollama)
├── intent/         # Natural-language query → service / time-window / log-level extraction
└── models/         # SQLModel tables: log_chunks, investigations, watcher_configs, offsets
worker.py           # Background file watcher — polls watcher_configs, ingests new log bytes
```

## Quick Start

### 1. Start infrastructure

```bash
docker-compose up -d db redis
```

### 2. Install dependencies

```bash
poetry install
```

### 3. Configure environment

Create a `.env` file:

```env
DATABASE_URL=postgresql+asyncpg://lograg_user:password_here@localhost:5432/lograg
LLM_PROVIDER=anthropic          # openai | anthropic | mistral | gemini | ollama
ANTHROPIC_API_KEY=sk-ant-...    # or OPENAI_API_KEY / MISTRAL_API_KEY / GEMINI_API_KEY
```

### 4. Start the API

Migrations run automatically on startup.

```bash
make serve
# → http://localhost:8000
# → http://localhost:8000/docs  (Swagger UI)
```

## Usage

### Ingest a log file manually

```bash
curl -X POST \
  -F "service=my-service" \
  -F "file=@/path/to/app.log" \
  http://localhost:8000/ingest
```

### Investigate

```bash
curl -X POST http://localhost:8000/investigate \
  -H "Content-Type: application/json" \
  -d '{"query": "why did checkout fail last friday night"}'
```

Stream the ReAct steps live:

```bash
curl -N http://localhost:8000/investigate/{id}/stream
```

### Continuous ingestion with the Worker

The worker watches directories for new log bytes and ingests them automatically.

1. Register a watcher via the API:

```bash
curl -X POST http://localhost:8000/watchers \
  -H "Content-Type: application/json" \
  -d '{"service_name": "auth-svc", "watch_path": "/var/log/auth"}'
```

2. Start the worker:

```bash
poetry run python -m repi.worker
```

The worker polls `watcher_configs` every 30s (`WATCHER_CONFIG_REFRESH_SECS`) and uses `watchfiles` to detect new bytes, seeking forward from the last stored offset.

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `DATABASE_URL` | `postgresql+asyncpg://postgres:postgres@localhost:5432/lograg` | PostgreSQL asyncpg URL |
| `LLM_PROVIDER` | `openai` | `openai` \| `anthropic` \| `mistral` \| `gemini` \| `ollama` |
| `LLM_MODEL` | provider default | Override model name |
| `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` / … | — | Provider API key |
| `REDIS_URL` | `redis://localhost:6379` | Redis for caching |
| `ENABLE_REDIS_CACHE` | `true` | Set `false` to disable Redis |
| `TIME_WINDOW_INITIAL_MINUTES` | `10` | First search window for investigation |
| `TIME_WINDOW_EXPANSIONS` | `60,360,1440` | Progressive window expansion (minutes) |
| `WATCHER_CONFIG_REFRESH_SECS` | `30` | How often the worker polls for config changes |
| `OLLAMA_BASE_URL` | `http://localhost:11434` | Ollama endpoint |

## Development

```bash
# Run all tests
poetry run pytest tests/ -v

# Run worker tests only
poetry run pytest tests/worker/ -v

# Run investigation tests
poetry run pytest tests/investigation/ -v
```

## License

MIT
