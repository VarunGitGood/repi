# repi

Local-first log investigation engine. repi ingests logs into PostgreSQL, indexes them with hybrid retrieval (pgvector HNSW + ParadeDB BM25, fused with Reciprocal Rank Fusion), clusters events by signature, and runs an autonomous ReAct loop to trace root causes across services. Logs and investigations live in projects so different services / environments stay separated. Runs on a single machine against a local Postgres no SaaS, no shared state.

## Architecture

```
repi/
├── cli.py          # Typer CLI — lifecycle commands: init, serve, ui, stop
├── worker.py       # Background file watcher — polls watcher_configs, ingests new log bytes
├── api/            # FastAPI — ingest, chat, investigate, conversations, projects, watchers, config endpoints
├── core/           # Settings (pydantic-settings), DI container, Redis cache
├── ingestion/      # Log parsing → signature clustering → embedding → upsert
├── retrieval/      # pgvector HNSW + ParadeDB BM25, RRF fusion, query expansion, timeline + cluster views
├── investigation/  # ReAct gather loop + separate compile-LLM step, tools, evidence store
├── llm/            # Provider protocol + adapters (OpenAI, Anthropic, Mistral, Gemini, Ollama)
├── intent/         # Natural-language query → service / time-window / log-level extraction
└── models/         # SQLModel tables: projects, log_chunks, conversations, chat_messages,
                    #                  investigations, investigation_steps, investigation_chunks,
                    #                  watcher_configs, watcher_offsets
```

The Next.js web UI (`web/`) is the recommended surface. It drives the same FastAPI endpoints below.

## Getting started

There are two supported ways to run repi. Pick one.

### Run it (Docker only)

The fastest path. No clone, no Python toolchain, no Node. Multi-arch images (linux/amd64 + linux/arm64) are published to GHCR on every push to `main` and every tagged release. The image bundles the FastAPI backend (`:8000`) and the Next.js UI (`:3000`) in one container.

**Prerequisites:** Docker.

```bash
# Grab the compose file (defines db + redis + the repi app image from GHCR)
curl -O https://raw.githubusercontent.com/VarunGitGood/repi/main/docker-compose.yml

# Bring up Postgres + Redis + repi (backend + UI)
docker compose up -d

# Open the UI, visit /config, paste your LLM provider key, save.
open http://localhost:3000
```

On first start, the entrypoint seeds `/app/.repi/config.json` from a baked-in default into a named volume (`repi_config`). The seed has docker-internal infra URLs and an empty LLM key, so:

- `/health` returns `{"llm_configured": false, ...}` and `/investigate` returns 409 until a key is supplied.
- Visit the **Config** page in the UI, pick a provider, paste your API key, save. The API hot-reloads.
- Your config persists across `docker compose down` (lost only on `down -v`).

Pin a release via `REPI_IMAGE=ghcr.io/varungitgood/repi:0.2.0 docker compose up -d`.

### Hack on it (contributor / dev path)

For editing the codebase with hot-reload + breakpoints. Docker runs only the infra (Postgres + Redis); backend and UI run on the host so changes pick up instantly.

**Prerequisites:** Docker, Python 3.11+, [`uv`](https://docs.astral.sh/uv/), Node.js.

```bash
git clone https://github.com/VarunGitGood/repi.git && cd repi
uv sync                                 # resolve lockfile into .venv
uv run repi init --with-docker          # db + redis up, prompts provider/key, writes .repi/config.json, applies schema
uv run repi serve                       # terminal 1: API on :8000 (auto-reload in development)
uv run repi ui                          # terminal 2: web UI on :3000 (Next.js HMR)
uv run repi stop                        # when done: tear down docker stack
```

### Configuration

`.repi/config.json` is the **sole** source of truth. Shell env vars and `.env` files are ignored at runtime there is no env-var fallback. The file is gitignored.

Three ways to edit it, in order of convenience:
1. **Web UI** visit the Config page; changes save immediately and the API hot-reloads them.
2. **Re-run `repi init --force`** re-prompts for provider + key and rewrites the file.
3. **Edit the JSON directly** `.repi/config.json` is plain JSON; restart the API after editing.

`REPI_ENV` defaults to `production`. Flip to `development` in `.repi/config.json` (or via the UI) for verbose logs + `--reload`.

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

## Configuration keys

All keys live in `.repi/config.json` (see `config.example.json` for the full schema). Setting them in the shell or a `.env` file does nothing — Settings reads only this file.

| Key | Default | Description |
|----------|---------|-------------|
| `REPI_ENV` | `production` | `production` \| `development`. Production = quiet logs, no auto-reload. |
| `LOG_LEVEL` | `INFO` | `DEBUG` \| `INFO` \| `WARNING` \| `ERROR`. |
| `DATABASE_URL` | `postgresql+asyncpg://repi_user:password_here@localhost:5432/repi` | PostgreSQL asyncpg URL. The docker image ships a docker-aware default (`db:5432`). |
| `LLM_PROVIDER` | `openai` | `openai` \| `anthropic` \| `mistral` \| `gemini` \| `ollama` |
| `LLM_MODEL` | provider default | Override model name |
| `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` / `MISTRAL_API_KEY` / `GEMINI_API_KEY` / `LLM_API_KEY` | — | Provider API key. Set the one that matches your `LLM_PROVIDER`. |
| `REDIS_URL` | `redis://localhost:6379` | Redis for caching |
| `ENABLE_REDIS_CACHE` | `true` | Set `false` to disable Redis |
| `TIME_WINDOW_INITIAL_MINUTES` | `10` | First search window for investigation |
| `TIME_WINDOW_EXPANSIONS` | `60,360,1440` | Progressive window expansion (minutes) |
| `UI_PORT` | `3000` | Port the web UI binds to (read by `repi ui`) |
| `WATCHER_CONFIG_REFRESH_SECS` | `30` | How often the worker polls for config changes |
| `OLLAMA_BASE_URL` | `http://localhost:11434` | Ollama endpoint |
| `LLM_MAX_CALLS_PER_MIN` | `10` | Maximum LLM API calls per minute in the ReAct loop. Increase for high-tier API plans. |

## Development

```bash
# Run all tests
uv run pytest tests/ -v

# Run a single file
uv run pytest tests/investigation/test_react_loop.py -v

# Investigation eval — three scripted datasets graded against expected.json
uv run python eval/run_evals.py

# RAGAS retrieval eval — measures retrieval quality in isolation
uv run python eval/ragas_eval.py --skip-ragas          # fast: retrieval metrics only
uv run python eval/ragas_eval.py --evaluator-provider mistral  # full: includes LLM-judged RAGAS scores
uv run python eval/ragas_eval.py --dataset ragas_loghub_real   # single dataset
```

## Contributing

Bug reports and feature requests go in [GitHub Issues](https://github.com/VarunGitGood/repi/issues). PRs welcome — tests should pass (`uv run pytest tests/ -q`) and the docker image should still build.

## License

[MIT](./LICENSE).
