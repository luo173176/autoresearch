-- 阶段 8：后台任务编排与幂等

CREATE TABLE IF NOT EXISTS jobs (
    id BIGSERIAL PRIMARY KEY,
    project_id BIGINT REFERENCES projects(id) ON DELETE SET NULL,
    type TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'queued',
    progress INTEGER NOT NULL DEFAULT 0 CHECK (progress BETWEEN 0 AND 100),
    current_step TEXT NOT NULL DEFAULT 'queued',
    input JSONB,
    output JSONB,
    error TEXT,
    idempotency_key TEXT UNIQUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    started_at TIMESTAMPTZ,
    finished_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS jobs_project_idx ON jobs (project_id, id DESC);
CREATE INDEX IF NOT EXISTS jobs_status_idx ON jobs (status, id DESC);
