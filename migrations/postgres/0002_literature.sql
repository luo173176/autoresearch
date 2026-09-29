-- 阶段 1：项目—论文关联表（papers 全局去重共享，通过关联表挂到项目）

CREATE TABLE IF NOT EXISTS projects_papers (
    id          BIGSERIAL PRIMARY KEY,
    project_id  BIGINT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    paper_id    BIGINT NOT NULL REFERENCES papers(id) ON DELETE CASCADE,
    query       TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS projects_papers_uidx ON projects_papers (project_id, paper_id);
CREATE INDEX IF NOT EXISTS projects_papers_project_idx ON projects_papers (project_id);
