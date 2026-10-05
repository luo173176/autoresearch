from fastapi.testclient import TestClient

from autoresearch.api.main import create_app
from autoresearch.jobs import JobManager


def test_api_key_protects_business_routes(test_settings, db):
    secured = test_settings.model_copy(update={"api_key": "m3-secret"})
    with TestClient(create_app(secured)) as client:
        health = client.get("/health")
        assert health.status_code == 200
        assert client.post("/projects", json={"name": "x", "question": "q"}).status_code == 401
        assert (
            client.post(
                "/projects",
                headers={"Authorization": "Bearer m3-secret"},
                json={"name": "x", "question": "q"},
            ).status_code
            == 201
        )


def test_request_id_and_metrics(test_settings, db):
    with TestClient(create_app(test_settings)) as client:
        response = client.get("/health", headers={"X-Request-ID": "trace-m3"})
        assert response.headers["X-Request-ID"] == "trace-m3"
        assert int(response.headers["X-Process-Time-ms"]) >= 0
        metrics = client.get("/metrics").json()
        assert metrics["requests_total"] >= 1
        assert "jobs_active" in metrics


def test_startup_recovers_unfinished_job(test_settings, db):
    manager = JobManager(test_settings)
    job, _ = manager.create(db, job_type="test", project_id=None, payload={})
    db.execute(
        f"UPDATE jobs SET status = {db.ph}, current_step = {db.ph} WHERE id = {db.ph}",
        ["running", "working", job["id"]],
    )
    recovered = manager.recover(db)
    assert recovered == 1
    row = db.query_one(f"SELECT * FROM jobs WHERE id = {db.ph}", [job["id"]])
    assert row["status"] == "failed"
    assert row["current_step"] == "interrupted"
    manager.close()
