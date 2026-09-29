-- AutoResearch 初始 schema（PostgreSQL 16 + JSONB）
-- 说明：embedding 向量列（pgvector）在阶段 1/2 引入嵌入流水线时由 0002 迁移添加，
--       以保证 0001 在双后端（PG/SQLite）下保持同构可执行。

CREATE TABLE IF NOT EXISTS projects (
    id          BIGSERIAL PRIMARY KEY,
    name        TEXT NOT NULL,
    question    TEXT NOT NULL,
    domain      TEXT NOT NULL DEFAULT 'general',
    budget      JSONB NOT NULL DEFAULT '{}'::jsonb,
    status      TEXT NOT NULL DEFAULT 'active',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS papers (
    id          BIGSERIAL PRIMARY KEY,
    title       TEXT NOT NULL,
    authors     JSONB NOT NULL DEFAULT '[]'::jsonb,
    year        INTEGER,
    venue       TEXT,
    abstract    TEXT,
    url         TEXT,
    pdf_path    TEXT,
    dedupe_key  TEXT,
    metadata    JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS papers_dedupe_uidx ON papers (dedupe_key);
CREATE INDEX IF NOT EXISTS papers_year_idx ON papers (year);

CREATE TABLE IF NOT EXISTS chunks (
    id          BIGSERIAL PRIMARY KEY,
    paper_id    BIGINT NOT NULL REFERENCES papers(id) ON DELETE CASCADE,
    text        TEXT NOT NULL,
    summary     TEXT,
    keywords    JSONB NOT NULL DEFAULT '[]'::jsonb,
    entities    JSONB NOT NULL DEFAULT '[]'::jsonb,
    metadata    JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS chunks_paper_idx ON chunks (paper_id);

CREATE TABLE IF NOT EXISTS entities (
    id          BIGSERIAL PRIMARY KEY,
    name        TEXT NOT NULL,
    type        TEXT NOT NULL,
    metadata    JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS entities_name_type_uidx ON entities (lower(name), type);

CREATE TABLE IF NOT EXISTS relations (
    id                BIGSERIAL PRIMARY KEY,
    source_entity_id  BIGINT NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
    target_entity_id  BIGINT NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
    type              TEXT NOT NULL,
    evidence          JSONB NOT NULL DEFAULT '[]'::jsonb,
    confidence        REAL NOT NULL DEFAULT 0.5,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS relations_source_idx ON relations (source_entity_id);
CREATE INDEX IF NOT EXISTS relations_target_idx ON relations (target_entity_id);
CREATE UNIQUE INDEX IF NOT EXISTS relations_triple_uidx ON relations (source_entity_id, target_entity_id, type);

CREATE TABLE IF NOT EXISTS hypotheses (
    id           BIGSERIAL PRIMARY KEY,
    project_id   BIGINT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    statement    TEXT NOT NULL,
    rationale    TEXT,
    testability  JSONB NOT NULL DEFAULT '{}'::jsonb,
    novelty      REAL NOT NULL DEFAULT 0.5,
    status       TEXT NOT NULL DEFAULT 'proposed',
    metadata     JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS hypotheses_project_idx ON hypotheses (project_id);

CREATE TABLE IF NOT EXISTS experiments (
    id            BIGSERIAL PRIMARY KEY,
    hypothesis_id BIGINT NOT NULL REFERENCES hypotheses(id) ON DELETE CASCADE,
    design        JSONB NOT NULL DEFAULT '{}'::jsonb,
    datasets      JSONB NOT NULL DEFAULT '[]'::jsonb,
    baselines     JSONB NOT NULL DEFAULT '[]'::jsonb,
    metrics       JSONB NOT NULL DEFAULT '[]'::jsonb,
    status        TEXT NOT NULL DEFAULT 'designed',
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS experiments_hypothesis_idx ON experiments (hypothesis_id);

CREATE TABLE IF NOT EXISTS runs (
    id            BIGSERIAL PRIMARY KEY,
    experiment_id BIGINT NOT NULL REFERENCES experiments(id) ON DELETE CASCADE,
    code_path     TEXT,
    config        JSONB NOT NULL DEFAULT '{}'::jsonb,
    metrics       JSONB NOT NULL DEFAULT '{}'::jsonb,
    logs          TEXT,
    status        TEXT NOT NULL DEFAULT 'pending',
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS runs_experiment_idx ON runs (experiment_id);

CREATE TABLE IF NOT EXISTS reports (
    id          BIGSERIAL PRIMARY KEY,
    project_id  BIGINT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    content     TEXT,
    citations   JSONB NOT NULL DEFAULT '[]'::jsonb,
    figures     JSONB NOT NULL DEFAULT '[]'::jsonb,
    status      TEXT NOT NULL DEFAULT 'draft',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS reports_project_idx ON reports (project_id);

CREATE TABLE IF NOT EXISTS qa_logs (
    id           BIGSERIAL PRIMARY KEY,
    question     TEXT NOT NULL,
    answer       TEXT,
    citations    JSONB NOT NULL DEFAULT '[]'::jsonb,
    confidence   REAL,
    latency_ms   INTEGER,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
