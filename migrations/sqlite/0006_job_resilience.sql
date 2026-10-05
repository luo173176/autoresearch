-- 阶段 9：任务恢复与可观测性

ALTER TABLE jobs ADD COLUMN attempt_count INTEGER NOT NULL DEFAULT 0;
ALTER TABLE jobs ADD COLUMN heartbeat_at TEXT;
ALTER TABLE jobs ADD COLUMN worker_id TEXT;

CREATE INDEX IF NOT EXISTS jobs_heartbeat_idx ON jobs (status, heartbeat_at);
