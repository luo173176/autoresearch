-- 阶段 9：任务恢复与可观测性

ALTER TABLE jobs ADD COLUMN IF NOT EXISTS attempt_count INTEGER NOT NULL DEFAULT 0;
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS heartbeat_at TIMESTAMPTZ;
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS worker_id TEXT;

CREATE INDEX IF NOT EXISTS jobs_heartbeat_idx ON jobs (status, heartbeat_at);
