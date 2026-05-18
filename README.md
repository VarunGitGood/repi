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

## Install & run

Four distribution paths. Only **1. Local flow** works today — the rest are placeholders for future releases.

### 1. Local flow (from a fresh clone)

The supported path right now. Use this for contributing or for running against your own data while the package distributions are still WIP.

**Prerequisites:** Docker, Python 3.11+, [`uv`](https://docs.astral.sh/uv/), Node.js (for the web UI).

```bash
git clone https://github.com/VarunGitGood/repi.git
cd repi
uv sync                                 # resolve lockfile into .venv
uv run repi init --with-docker          # db + redis up, prompts provider/key, writes .repi/config.json, applies schema
uv run repi serve                       # terminal 1: API on :8000
uv run repi ui                          # terminal 2: web UI on :3000
uv run repi stop                        # when done: tear down docker stack
```

### 2. Homebrew — 🚧 WIP

Planned formula: `brew install repi`. Will bundle the CLI and bring up the Postgres + Redis dependencies via `brew services` rather than Docker.

Not available yet.

### 3. Docker image — 🚧 WIP

Planned: a published image on a registry (`ghcr.io/varungitgood/repi`) so a single `docker compose up` brings up `repi-api`, `repi-worker`, Postgres (pgvector), and Redis without needing the source tree.

Not available yet. The local `docker-compose.yml` in this repo currently only provisions Postgres + Redis for the local flow above — it does not run the API itself.

### 4. PyPI package — 🚧 WIP

Planned end-user flow once published:

```bash
pipx install repi               # or: uv tool install repi
repi init --with-docker
repi serve
repi ui
```

**Steps to publish (todo):**

1. Pin `pyproject.toml` metadata (`version`, `description`, `authors`, `license`, `readme`, `classifiers`, `urls`).
2. Verify `[project.scripts] repi = "repi.cli:main"` resolves with `uv build`.
3. Audit bundled assets — `web/` (Next.js) is currently not packaged; decide whether to ship it inside the wheel, fetch it on first `repi ui`, or split into a separate `repi-ui` package.
4. `uv build` → produces `dist/repi-<version>.tar.gz` + wheel.
5. Smoke-test in a clean venv: `pipx install ./dist/repi-*.whl && repi --help`.
6. Tag the release (`vX.Y.Z`) and push.
7. `uv publish --token <PYPI_API_TOKEN>` (or via a GitHub Action triggered on tag).
8. Verify `pipx install repi` works end-to-end from PyPI.

Not available yet.

---

### Configuration

repi has **one source of truth**: `.repi/config.json`. It's created by `repi init` and mutated by the web UI's Config page (`PUT /config`). The file is gitignored.

Three ways to edit it, in order of convenience:
1. **Web UI** — visit the Config page; changes save immediately and the API hot-reloads them.
2. **Re-run `repi init --force`** — re-prompts for provider + key and rewrites the file.
3. **Edit the JSON directly** — `.repi/config.json` is plain JSON; restart the API after editing.

Shell env vars (e.g. `REPI_ENV=development uv run repi serve`) override values from `config.json` at runtime — handy for one-off commands or CI.

`REPI_ENV` defaults to `production`. Flip to `development` in `.repi/config.json` (or via the UI) for verbose logs + `--reload`.

> **Coming from an older checkout?** If you have a legacy `config.json` at the repo root, move it: `mkdir -p .repi && mv config.json .repi/config.json`. The root `config.json` is no longer read.

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
uv run python -m repi.worker
```

The worker polls `watcher_configs` every 30s (`WATCHER_CONFIG_REFRESH_SECS`) and uses `watchfiles` to detect new bytes, seeking forward from the last stored offset.

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `REPI_ENV` | `production` | `production` \| `development`. Production = quiet logs, no auto-reload. |
| `DATABASE_URL` | `postgresql+asyncpg://lograg_user:password_here@localhost:5432/lograg` | PostgreSQL asyncpg URL |
| `LLM_PROVIDER` | `openai` | `openai` \| `anthropic` \| `mistral` \| `gemini` \| `ollama` |
| `LLM_MODEL` | provider default | Override model name |
| `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` / … | — | Provider API key |
| `REDIS_URL` | `redis://localhost:6379` | Redis for caching |
| `ENABLE_REDIS_CACHE` | `true` | Set `false` to disable Redis |
| `TIME_WINDOW_INITIAL_MINUTES` | `10` | First search window for investigation |
| `TIME_WINDOW_EXPANSIONS` | `60,360,1440` | Progressive window expansion (minutes) |
| `UI_PORT` | `3000` | Port the web UI binds to (read by `repi ui`) |
| `WATCHER_CONFIG_REFRESH_SECS` | `30` | How often the worker polls for config changes |
| `OLLAMA_BASE_URL` | `http://localhost:11434` | Ollama endpoint |

## Development

```bash
# Run all tests
uv run pytest tests/ -v

# Run worker tests only
uv run pytest tests/worker/ -v

# Run investigation tests
uv run pytest tests/investigation/ -v
```

## License

MIT
