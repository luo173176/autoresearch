-- AutoResearch 初始 schema（SQLite 零依赖本地模式；JSON 列以 TEXT 存储）
-- 与 migrations/postgres/0001_init.sql 保持同构。

CREATE TABLE IF NOT EXISTS projects (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL,
    question    TEXT NOT NULL,
    domain      TEXT NOT NULL DEFAULT 'general',
    budget      TEXT NOT NULL DEFAULT '{}',
    status      TEXT NOT NULL DEFAULT 'active',
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS papers (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    title       TEXT NOT NULL,
    authors     TEXT NOT NULL DEFAULT '[]',
    year        INTEGER,
    venue       TEXT,
    abstract    TEXT,
    url         TEXT,
    pdf_path    TEXT,
    dedupe_key  TEXT,
    metadata    TEXT NOT NULL DEFAULT '{}',
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE UNIQUE INDEX IF NOT EXISTS papers_dedupe_uidx ON papers (dedupe_key);
CREATE INDEX IF NOT EXISTS papers_year_idx ON papers (year);

CREATE TABLE IF NOT EXISTS chunks (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    paper_id    INTEGER NOT NULL REFERENCES papers(id) ON DELETE CASCADE,
    text        TEXT NOT NULL,
    summary     TEXT,
    keywords    TEXT NOT NULL DEFAULT '[]',
    entities    TEXT NOT NULL DEFAULT '[]',
    metadata    TEXT NOT NULL DEFAULT '{}',
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS chunks_paper_idx ON chunks (paper_id);

CREATE TABLE IF NOT EXISTS entities (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL,
    type        TEXT NOT NULL,
    metadata    TEXT NOT NULL DEFAULT '{}',
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE UNIQUE INDEX IF NOT EXISTS entities_name_type_uidx ON entities (lower(name), type);

CREATE TABLE IF NOT EXISTS relations (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    source_entity_id  INTEGER NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
    target_entity_id  INTEGER NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
    type              TEXT NOT NULL,
    evidence          TEXT NOT NULL DEFAULT '[]',
    confidence        REAL NOT NULL DEFAULT 0.5,
    created_at        TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS relations_source_idx ON relations (source_entity_id);
CREATE INDEX IF NOT EXISTS relations_target_idx ON relations (target_entity_id);
CREATE UNIQUE INDEX IF NOT EXISTS relations_triple_uidx ON relations (source_entity_id, target_entity_id, type);

CREATE TABLE IF NOT EXISTS hypotheses (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id   INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    statement    TEXT NOT NULL,
    rationale    TEXT,
    testability  TEXT NOT NULL DEFAULT '{}',
    novelty      REAL NOT NULL DEFAULT 0.5,
    status       TEXT NOT NULL DEFAULT 'proposed',
    metadata     TEXT NOT NULL DEFAULT '{}',
    created_at   TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS hypotheses_project_idx ON hypotheses (project_id);

CREATE TABLE IF NOT EXISTS experiments (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    hypothesis_id INTEGER NOT NULL REFERENCES hypotheses(id) ON DELETE CASCADE,
    design        TEXT NOT NULL DEFAULT '{}',
    datasets      TEXT NOT NULL DEFAULT '[]',
    baselines     TEXT NOT NULL DEFAULT '[]',
    metrics       TEXT NOT NULL DEFAULT '[]',
    status        TEXT NOT NULL DEFAULT 'designed',
    created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS experiments_hypothesis_idx ON experiments (hypothesis_id);

CREATE TABLE IF NOT EXISTS runs (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    experiment_id INTEGER NOT NULL REFERENCES experiments(id) ON DELETE CASCADE,
    code_path     TEXT,
    config        TEXT NOT NULL DEFAULT '{}',
    metrics       TEXT NOT NULL DEFAULT '{}',
    logs          TEXT,
    status        TEXT NOT NULL DEFAULT 'pending',
    created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS runs_experiment_idx ON runs (experiment_id);

CREATE TABLE IF NOT EXISTS reports (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id  INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    content     TEXT,
    citations   TEXT NOT NULL DEFAULT '[]',
    figures     TEXT NOT NULL DEFAULT '[]',
    status      TEXT NOT NULL DEFAULT 'draft',
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS reports_project_idx ON reports (project_id);

CREATE TABLE IF NOT EXISTS qa_logs (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    question     TEXT NOT NULL,
    answer       TEXT,
    citations    TEXT NOT NULL DEFAULT '[]',
    confidence   REAL,
    latency_ms   INTEGER,
    created_at   TEXT NOT NULL DEFAULT (datetime('now'))
);
