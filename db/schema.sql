-- repi database schema
-- All statements are idempotent; safe to run on every startup.

CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;

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
CREATE INDEX IF NOT EXISTS log_chunks_source_service_idx ON log_chunks (source_service);
CREATE INDEX IF NOT EXISTS log_chunks_log_level_idx      ON log_chunks (log_level);
CREATE INDEX IF NOT EXISTS log_chunks_timestamp_idx      ON log_chunks (timestamp_start);
CREATE INDEX IF NOT EXISTS log_chunks_text_trgm_idx       ON log_chunks USING gin (text gin_trgm_ops);
CREATE INDEX IF NOT EXISTS log_chunks_service_trgm_idx    ON log_chunks USING gin (source_service gin_trgm_ops);

ALTER TABLE log_chunks
    ADD COLUMN IF NOT EXISTS text_tsv tsvector
    GENERATED ALWAYS AS (
        setweight(to_tsvector('english', coalesce(text, '')), 'A') ||
        setweight(to_tsvector('english', coalesce(source_service, '')), 'B') ||
        setweight(to_tsvector('english', coalesce(log_level, '')), 'C')
    ) STORED;

DROP INDEX IF EXISTS log_chunks_fts_idx;
CREATE INDEX IF NOT EXISTS log_chunks_text_tsv_idx ON log_chunks USING gin (text_tsv);

CREATE TABLE IF NOT EXISTS conversations (
    id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    title      TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS conversations_updated_at_idx ON conversations (updated_at DESC);

CREATE TABLE IF NOT EXISTS chat_messages (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    conversation_id UUID NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    role            TEXT NOT NULL,
    content         TEXT NOT NULL,
    chunk_ids       TEXT[] NOT NULL DEFAULT '{}',
    confidence      TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS chat_messages_conv_idx ON chat_messages (conversation_id, created_at);

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
    pending_question   TEXT,
    conversation_id    UUID REFERENCES conversations(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS investigations_status_idx     ON investigations (status);
CREATE INDEX IF NOT EXISTS investigations_created_at_idx ON investigations (created_at DESC);
CREATE INDEX IF NOT EXISTS investigations_conv_idx       ON investigations (conversation_id, created_at);

-- Idempotent add for older DBs that pre-date the chat surface.
ALTER TABLE investigations
    ADD COLUMN IF NOT EXISTS conversation_id UUID REFERENCES conversations(id) ON DELETE SET NULL;

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

-- Distinguish runs by embedding backend (torch vs fastembed).
ALTER TABLE leaderboard
    ADD COLUMN IF NOT EXISTS embedding_backend TEXT NOT NULL DEFAULT 'unknown';

CREATE INDEX IF NOT EXISTS leaderboard_run_idx     ON leaderboard (run_id);
CREATE INDEX IF NOT EXISTS leaderboard_model_idx   ON leaderboard (model);
CREATE INDEX IF NOT EXISTS leaderboard_dataset_idx ON leaderboard (dataset);
CREATE INDEX IF NOT EXISTS leaderboard_score_idx   ON leaderboard (dataset, aggregate_score DESC);
CREATE INDEX IF NOT EXISTS leaderboard_created_idx ON leaderboard (created_at DESC);
CREATE INDEX IF NOT EXISTS leaderboard_backend_idx ON leaderboard (embedding_backend);

-- ── Projects (UX redesign P1) ────────────────────────────────────────────────
-- A project is a logical system/application (e.g. "Ecommerce Platform").
-- Workers, services (via log_chunks), conversations and investigations are
-- scoped to a project. `settings` keys: default_timeline_window ("5h"),
-- auto_load_timeline (true), max_events (25) — read by /projects/{id}/overview.
CREATE TABLE IF NOT EXISTS projects (
    id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name       TEXT UNIQUE NOT NULL,
    settings   JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE log_chunks      ADD COLUMN IF NOT EXISTS project_id UUID REFERENCES projects(id) ON DELETE SET NULL;
ALTER TABLE watcher_configs ADD COLUMN IF NOT EXISTS project_id UUID REFERENCES projects(id) ON DELETE SET NULL;
ALTER TABLE conversations   ADD COLUMN IF NOT EXISTS project_id UUID REFERENCES projects(id) ON DELETE SET NULL;
ALTER TABLE investigations  ADD COLUMN IF NOT EXISTS project_id UUID REFERENCES projects(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS log_chunks_project_ts_idx ON log_chunks (project_id, timestamp_start);

-- Real signature column ("Path B" from cluster_view.py): enables corpus-wide
-- GROUP BY signature for the project overview's clusters and event feed,
-- instead of re-parsing it out of `text` per row in Python. The ingestor
-- writes it for new rows; the UPDATE below backfills pre-existing rows from
-- the templated text body ("Signature: <sig>\nExamples: ...").
ALTER TABLE log_chunks ADD COLUMN IF NOT EXISTS signature TEXT;
UPDATE log_chunks
    SET signature = split_part(split_part(text, E'\n', 1), 'Signature: ', 2)
    WHERE signature IS NULL;
CREATE INDEX IF NOT EXISTS log_chunks_signature_idx ON log_chunks (project_id, signature);

-- Seed a Default project on first run and absorb all pre-project rows into it.
-- Idempotent: the seed only fires when `projects` is empty, and the backfills
-- only touch NULL project_id rows.
DO $$
DECLARE
    default_id UUID;
BEGIN
    IF NOT EXISTS (SELECT 1 FROM projects) THEN
        INSERT INTO projects (name) VALUES ('Default');
    END IF;
    SELECT id INTO default_id FROM projects WHERE name = 'Default';
    IF default_id IS NOT NULL THEN
        UPDATE log_chunks      SET project_id = default_id WHERE project_id IS NULL;
        UPDATE watcher_configs SET project_id = default_id WHERE project_id IS NULL;
        UPDATE conversations   SET project_id = default_id WHERE project_id IS NULL;
        UPDATE investigations  SET project_id = default_id WHERE project_id IS NULL;
    END IF;
END $$;
