-- repi database schema
-- All statements are idempotent; safe to run on every startup.

CREATE EXTENSION IF NOT EXISTS vector;

-- Log chunks: core ingestion table
CREATE TABLE IF NOT EXISTS log_chunks (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    chunk_id        TEXT UNIQUE NOT NULL,
    source_service  TEXT NOT NULL,
    source_env      TEXT NOT NULL DEFAULT 'production',
    log_level       TEXT,
    component       TEXT,
    request_id      TEXT,
    timestamp_start TIMESTAMPTZ,
    timestamp_end   TIMESTAMPTZ,
    ingested_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    text            TEXT NOT NULL,
    id_values       TEXT[],
    embedding       vector(384),
    log_metadata    JSONB
);

CREATE INDEX IF NOT EXISTS log_chunks_embedding_idx      ON log_chunks USING hnsw (embedding vector_ip_ops);
CREATE INDEX IF NOT EXISTS log_chunks_fts_idx            ON log_chunks USING gin  (to_tsvector('english', text));
CREATE INDEX IF NOT EXISTS log_chunks_source_service_idx ON log_chunks (source_service);
CREATE INDEX IF NOT EXISTS log_chunks_log_level_idx      ON log_chunks (log_level);
CREATE INDEX IF NOT EXISTS log_chunks_timestamp_idx      ON log_chunks (timestamp_start);

-- Investigations: ReAct loop sessions
CREATE TABLE IF NOT EXISTS investigations (
    id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    query              TEXT NOT NULL,
    status             TEXT NOT NULL DEFAULT 'started',
    created_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    current_step       INT NOT NULL DEFAULT 1,
    time_windows_tried JSONB NOT NULL DEFAULT '{}',
    services_seen      JSONB NOT NULL DEFAULT '[]',
    total_llm_calls    INT NOT NULL DEFAULT 0,
    answer             TEXT,
    pending_question   TEXT
);

CREATE INDEX IF NOT EXISTS investigations_status_idx     ON investigations (status);
CREATE INDEX IF NOT EXISTS investigations_created_at_idx ON investigations (created_at DESC);

-- Investigation steps: individual ReAct thought → action → observation records
CREATE TABLE IF NOT EXISTS investigation_steps (
    id               SERIAL PRIMARY KEY,
    investigation_id UUID NOT NULL REFERENCES investigations(id) ON DELETE CASCADE,
    step_number      INT NOT NULL,
    thought          TEXT NOT NULL,
    action           JSONB,
    observation      JSONB,
    kind             TEXT,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- kind classifies the step ("reflection" for forced re-plan turns, NULL for normal
-- thought→action→observation steps). Added idempotently for older DBs.
ALTER TABLE investigation_steps ADD COLUMN IF NOT EXISTS kind TEXT;

CREATE INDEX IF NOT EXISTS investigation_steps_inv_idx ON investigation_steps (investigation_id);

-- Investigation chunks: evidence collected per investigation
CREATE TABLE IF NOT EXISTS investigation_chunks (
    id               SERIAL PRIMARY KEY,
    investigation_id UUID NOT NULL REFERENCES investigations(id) ON DELETE CASCADE,
    chunk_id         TEXT NOT NULL,
    service          TEXT,
    timestamp        TIMESTAMPTZ,
    message          TEXT
);

CREATE INDEX IF NOT EXISTS investigation_chunks_inv_idx   ON investigation_chunks (investigation_id);
CREATE INDEX IF NOT EXISTS investigation_chunks_chunk_idx ON investigation_chunks (chunk_id);

-- Watcher configs: registered directories for continuous log ingestion
CREATE TABLE IF NOT EXISTS watcher_configs (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    service_name TEXT NOT NULL,
    watch_path   TEXT NOT NULL,
    env          TEXT NOT NULL DEFAULT 'production',
    enabled      BOOLEAN NOT NULL DEFAULT TRUE,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS watcher_configs_enabled_idx ON watcher_configs (enabled);
CREATE INDEX IF NOT EXISTS watcher_configs_service_idx ON watcher_configs (service_name);

-- Watcher offsets: per-file byte offset for incremental ingestion (restart-safe)
CREATE TABLE IF NOT EXISTS watcher_offsets (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    watcher_config_id UUID NOT NULL REFERENCES watcher_configs(id) ON DELETE CASCADE,
    file_path         TEXT NOT NULL,
    "offset"          BIGINT NOT NULL DEFAULT 0,
    last_seen_at      TIMESTAMPTZ,
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (watcher_config_id, file_path)
);

CREATE INDEX IF NOT EXISTS watcher_offsets_config_idx ON watcher_offsets (watcher_config_id);

-- Leaderboard: one row per (eval-run, dataset). Auto-written by eval/run_evals.py.
-- Used to track per-model scores across datasets over time.
CREATE TABLE IF NOT EXISTS leaderboard (
    id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id             UUID NOT NULL,
    provider           TEXT NOT NULL,
    model              TEXT NOT NULL,
    dataset            TEXT NOT NULL,
    aggregate_score    NUMERIC(4,3) NOT NULL,
    status             TEXT NOT NULL,
    judge_provider     TEXT NOT NULL,
    judge_model        TEXT NOT NULL,
    criteria           JSONB NOT NULL DEFAULT '[]',
    raw_judge_response TEXT,
    stats              JSONB NOT NULL DEFAULT '{}',
    created_at         TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS leaderboard_run_idx     ON leaderboard (run_id);
CREATE INDEX IF NOT EXISTS leaderboard_model_idx   ON leaderboard (model);
CREATE INDEX IF NOT EXISTS leaderboard_dataset_idx ON leaderboard (dataset);
CREATE INDEX IF NOT EXISTS leaderboard_score_idx   ON leaderboard (dataset, aggregate_score DESC);
CREATE INDEX IF NOT EXISTS leaderboard_created_idx ON leaderboard (created_at DESC);
