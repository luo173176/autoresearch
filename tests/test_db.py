import os

import pytest

from autoresearch.db import Database

TABLES = [
    "projects", "papers", "chunks", "entities", "relations",
    "hypotheses", "experiments", "runs", "reports", "qa_logs",
]


def test_migrate_creates_all_tables(db):
    names = {r["name"] for r in db.query("SELECT name FROM sqlite_master WHERE type='table'")}
    for t in TABLES:
        assert t in names, f"缺少表 {t}"


def test_migrate_idempotent(db):
    assert db.migrate() == []


def test_backend_defaults(test_settings):
    database = Database(test_settings)
    assert database.backend == "sqlite"
    assert database.ph == "?"


def test_fk_cascade(db):
    pid = db.insert(
        f"INSERT INTO projects (name, question) VALUES ({db.ph}, {db.ph})", ["t", "q"]
    )
    hid = db.insert(
        f"INSERT INTO hypotheses (project_id, statement) VALUES ({db.ph}, {db.ph})", [pid, "s"]
    )
    assert db.scalar("SELECT COUNT(*) FROM hypotheses") == 1
    db.execute(f"DELETE FROM projects WHERE id = {db.ph}", [pid])
    assert db.scalar("SELECT COUNT(*) FROM hypotheses") == 0
    assert hid > 0


def test_json_roundtrip(db):
    pid = db.insert(
        f"INSERT INTO projects (name, question, budget) VALUES ({db.ph}, {db.ph}, {db.ph})",
        ["j", "q", {"gpu_hours": 3, "tags": ["rag"]}],
    )
    row = db.query_one(f"SELECT budget FROM projects WHERE id = {db.ph}", [pid])
    assert row["budget"] == {"gpu_hours": 3, "tags": ["rag"]}


def test_postgres_optional(test_settings):
    url = os.environ.get("AUTORESEARCH_TEST_DATABASE_URL", "").strip()
    if not url:
        pytest.skip("未设置 AUTORESEARCH_TEST_DATABASE_URL，跳过 PostgreSQL 集成测试")
    database = Database(test_settings.model_copy(update={"database_url": url}))
    assert database.healthy()
    assert database.backend == "postgres"
    database.migrate()
