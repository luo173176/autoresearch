-- 阶段 12：项目级 API Key 范围、任务优先级

ALTER TABLE jobs ADD COLUMN priority INTEGER NOT NULL DEFAULT 0;
CREATE INDEX IF NOT EXISTS jobs_queue_priority_idx ON jobs (status, priority DESC, id ASC);
