import time

from fastapi.testclient import TestClient

from autoresearch.api.main import create_app
from autoresearch.jobs import JobManager
from autoresearch.worker import dispatch_pending


def test_project_scoped_api_key_filters_resources(test_settings, db):
    first = db.insert(
        f"INSERT INTO projects (name, question) VALUES ({db.ph}, {db.ph})", ["one", "q"]
    )
    second = db.insert(
        f"INSERT INTO projects (name, question) VALUES ({db.ph}, {db.ph})", ["two", "q"]
    )
    settings = test_settings.model_copy(
        update={"api_key": "project-secret", "api_key_project_id": first}
    )
    with TestClient(create_app(settings)) as client:
        headers = {"X-API-Key": "project-secret"}
        assert client.get("/projects", headers=headers).json()[0]["id"] == first
        assert client.get(f"/projects/{first}", headers=headers).status_code == 200
        assert client.get(f"/projects/{second}", headers=headers).status_code == 403


def test_rate_limit_returns_429(test_settings, db):
    settings = test_settings.model_copy(update={"rate_limit_per_minute": 1})
    with TestClient(create_app(settings)) as client:
        assert client.get("/projects").status_code == 200
        response = client.get("/projects")
        assert response.status_code == 429
        assert response.headers["Retry-After"] == "60"


def test_worker_dispatches_high_priority_first(test_settings, db):
    settings = test_settings.model_copy(update={"job_max_attempts": 1})
    manager = JobManager(settings, max_workers=1)
    low, _ = manager.create(
        db, job_type="unit", project_id=None, payload={"name": "low"}, priority=1
    )
    high, _ = manager.create(
        db, job_type="unit", project_id=None, payload={"name": "high"}, priority=90
    )
    seen = []

    def handler(job_db, update):
        seen.append(
            "high"
            if job_db.query_one(f"SELECT priority FROM jobs WHERE id = {job_db.ph}", [high["id"]])[
                "priority"
            ]
            == 90
            and len(seen) == 0
            else "low"
        )
        time.sleep(0.03)
        return {"ok": True}

    import autoresearch.worker as worker_module

    original = worker_module.handler_for_job
    worker_module.handler_for_job = lambda *_args: handler
    try:
        assert dispatch_pending(manager, db, settings, limit=2) == 2
        for _ in range(100):
            statuses = db.query(
                f"SELECT status FROM jobs WHERE id IN ({db.ph}, {db.ph}) ORDER BY id",
                [low["id"], high["id"]],
            )
            if all(row["status"] == "succeeded" for row in statuses):
                break
            time.sleep(0.02)
        assert seen[0] == "high"
    finally:
        worker_module.handler_for_job = original
        manager.close()
