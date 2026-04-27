CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS log_chunks (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    chunk_id    TEXT UNIQUE NOT NULL,
    source_service TEXT NOT NULL,
    source_env  TEXT NOT NULL DEFAULT 'production',
    log_level   TEXT,
    component   TEXT,
    request_id  TEXT,
    timestamp_start TIMESTAMPTZ,
    timestamp_end   TIMESTAMPTZ,
    ingested_at TIMESTAMPTZ DEFAULT NOW(),
    text        TEXT NOT NULL,
    id_values   TEXT[],
    embedding   vector(384),
    log_metadata    JSONB
);

CREATE INDEX IF NOT EXISTS log_chunks_embedding_idx ON log_chunks USING hnsw (embedding vector_ip_ops);
CREATE INDEX IF NOT EXISTS log_chunks_source_service_idx ON log_chunks (source_service);
CREATE INDEX IF NOT EXISTS log_chunks_log_level_idx ON log_chunks (log_level);
CREATE INDEX IF NOT EXISTS log_chunks_timestamp_start_idx ON log_chunks (timestamp_start);
CREATE INDEX IF NOT EXISTS log_chunks_fts_idx ON log_chunks USING GIN (to_tsvector('english', text));
