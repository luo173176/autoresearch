-- 阶段 13：数据库 API Key 注册表

CREATE TABLE IF NOT EXISTS api_keys (
    id BIGSERIAL PRIMARY KEY,
    key_prefix TEXT NOT NULL UNIQUE,
    key_hash TEXT NOT NULL UNIQUE,
    label TEXT NOT NULL DEFAULT '',
    project_id BIGINT REFERENCES projects(id) ON DELETE SET NULL,
    rate_limit_per_minute INTEGER NOT NULL DEFAULT 120 CHECK (rate_limit_per_minute >= 0),
    active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    revoked_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS api_keys_active_idx ON api_keys (active, id DESC);
CREATE INDEX IF NOT EXISTS api_keys_project_idx ON api_keys (project_id, active);
