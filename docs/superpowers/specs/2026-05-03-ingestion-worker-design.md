# Ingestion Worker Design

**Date:** 2026-05-03
**Status:** Approved

## Overview

A standalone background worker process that watches configured directories for new/appended log files and feeds them into the existing `LogIngestor` pipeline. Config is stored in the database and managed via new API endpoints (consumed by the UI's configure tab). Multiple worker instances can run in parallel against the same DB without coordination.

## Architecture

```
UI Configure Tab
      │
      ▼
FastAPI /watchers endpoints
      │  (CRUD)
      ▼
watcher_configs table ◄──── watcher_offsets table
      │                              ▲
      │ (poll every 30s)             │ (write after ingest)
      ▼                              │
repi/worker.py ──────────────────────┘
      │
      │ (watchfiles / inotify)
      ▼
Watched directories
      │
      │ (new bytes since last offset)
      ▼
LogIngestor.ingest()
      │
      ▼
pgvector (log_chunks table)
```

## Data Model

### `watcher_configs`

| Column         | Type      | Notes                              |
|----------------|-----------|------------------------------------|
| id             | UUID PK   | default uuid4                      |
| service_name   | str       | maps directory → service           |
| watch_path     | str       | absolute path on host              |
| env            | str       | default `"production"`             |
| enabled        | bool      | soft disable without deleting      |
| created_at     | datetime  |                                    |
| updated_at     | datetime  |                                    |

### `watcher_offsets`

| Column            | Type      | Notes                                   |
|-------------------|-----------|-----------------------------------------|
| id                | UUID PK   | default uuid4                           |
| watcher_config_id | UUID FK   | references watcher_configs.id           |
| file_path         | str       | absolute path to the specific file      |
| offset            | bigint    | byte offset — resume point on restart   |
| last_seen_at      | datetime  | last time this file had new content     |
| updated_at        | datetime  |                                         |

Offset is written **only after** a successful ingest. A crash mid-batch causes the same lines to be reprocessed on restart — safe because `LogIngestor` uses chunk signatures for deduplication.

## API Endpoints

All endpoints added as a new FastAPI router mounted at `/watchers`.

| Method | Path                     | Description                              |
|--------|--------------------------|------------------------------------------|
| POST   | `/watchers`              | Create a watcher config                  |
| GET    | `/watchers`              | List all watcher configs                 |
| PATCH  | `/watchers/{id}`         | Update a watcher (path, service, enable) |
| DELETE | `/watchers/{id}`         | Delete a watcher config                  |
| GET    | `/watchers/{id}/status`  | Show per-file offset + last_seen_at      |

No auth for now — dev tool assumption.

## Worker Process (`repi/worker.py`)

### Startup sequence

1. Connect to DB (same `DATABASE_URL` as API)
2. Load all `enabled=true` watcher configs
3. Load existing offsets from `watcher_offsets` (resume state)
4. Start `watchfiles.awatch()` across all configured paths
5. Start config-refresh loop (every 30s)

### Per-event handling

1. File change event arrives for path `P`
2. Look up current offset for `P` (default 0 if first seen)
3. Open file, seek to offset, read new bytes
4. Split into lines, discard empty
5. Call `LogIngestor.ingest(lines, service_name, env)`
6. On success: write new offset to `watcher_offsets`, update `last_seen_at`
7. On failure: log error, do **not** advance offset (will retry next event)

### Config refresh loop

Every 30s, re-query `watcher_configs`. New enabled watchers are added to the watch set. Disabled/deleted watchers are removed. No restart required.

### Graceful shutdown

On `SIGTERM`/`SIGINT`:
1. Stop accepting new file events
2. Finish current ingest batch
3. Flush all offsets to DB
4. Exit cleanly

### Scaling

Each worker instance is stateless beyond its DB-persisted offsets. To scale:
- Run multiple worker containers, each with a **non-overlapping** set of `watch_path` values
- No cross-worker coordination needed — offsets are per `(watcher_config_id, file_path)`

## New Dependency

`watchfiles` — async file watching via inotify (Linux) / FSEvents (Mac) / ReadDirectoryChanges (Windows). Lightweight, pure Python API over a Rust core.

## File Layout Changes

```
repi/
└── worker.py               # new — standalone worker entry point

repi/models/schema.py       # add WatcherConfig + WatcherOffset tables
repi/api/                   # new router split
│   ├── __init__.py
│   ├── ingest.py           # moved from api.py
│   ├── investigate.py      # moved from api.py
│   └── watchers.py         # new CRUD router
repi/api.py                 # kept as app factory, mounts routers

tests/
└── worker/
    ├── test_watcher.py         # e2e smoke: file created → ingestor called → offset saved
    └── test_offset_resume.py   # restart simulation: pre-load offset → only new lines processed
```

## Testing

### `test_watcher.py` — smoke test

- Write a temp log file with known content
- Mock DB session and `LogIngestor.ingest`
- Run one iteration of the watch loop
- Assert `ingest` called with correct lines and correct service name
- Assert offset written to DB equals file size after ingest

### `test_offset_resume.py` — resume test

- Create temp file with 10 lines
- Pre-load a `WatcherOffset` at byte position mid-file (after line 5)
- Run worker startup + one iteration
- Assert only lines 6–10 were passed to `ingest`
- Assert offset updated to end of file

Both tests mock DB and `LogIngestor` — no live postgres required, consistent with existing test patterns.

## Environment Variables

No new required vars. One optional addition:

| Variable                     | Default | Description                          |
|------------------------------|---------|--------------------------------------|
| `WATCHER_CONFIG_REFRESH_SECS`| `30`    | How often worker re-polls DB for config changes |
