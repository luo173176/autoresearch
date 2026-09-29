-- 阶段 1：项目—论文关联表（与 migrations/postgres/0002_literature.sql 同构）

CREATE TABLE IF NOT EXISTS projects_papers (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id  INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    paper_id    INTEGER NOT NULL REFERENCES papers(id) ON DELETE CASCADE,
    query       TEXT,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE UNIQUE INDEX IF NOT EXISTS projects_papers_uidx ON projects_papers (project_id, paper_id);
CREATE INDEX IF NOT EXISTS projects_papers_project_idx ON projects_papers (project_id);
