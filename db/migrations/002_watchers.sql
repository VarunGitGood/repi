CREATE TABLE IF NOT EXISTS watcher_configs (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    service_name TEXT NOT NULL,
    watch_path  TEXT NOT NULL,
    env         TEXT NOT NULL DEFAULT 'production',
    enabled     BOOLEAN NOT NULL DEFAULT TRUE,
    created_at  TIMESTAMPTZ DEFAULT NOW(),
    updated_at  TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS watcher_configs_enabled_idx ON watcher_configs (enabled);
CREATE INDEX IF NOT EXISTS watcher_configs_service_idx ON watcher_configs (service_name);

CREATE TABLE IF NOT EXISTS watcher_offsets (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    watcher_config_id   UUID NOT NULL REFERENCES watcher_configs(id) ON DELETE CASCADE,
    file_path           TEXT NOT NULL,
    "offset"            BIGINT NOT NULL DEFAULT 0,
    last_seen_at        TIMESTAMPTZ,
    updated_at          TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (watcher_config_id, file_path)
);

CREATE INDEX IF NOT EXISTS watcher_offsets_config_idx ON watcher_offsets (watcher_config_id);
