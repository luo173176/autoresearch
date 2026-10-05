import threading
import time

from fastapi.testclient import TestClient

from autoresearch.api.main import create_app
from autoresearch.jobs import JobManager


def _wait(db, job_id):
    for _ in range(100):
        row = db.query_one(f"SELECT * FROM jobs WHERE id = {db.ph}", [job_id])
        if row["status"] in {"succeeded", "failed", "cancelled"}:
            return row
        time.sleep(0.02)
    raise AssertionError(row)


def test_job_retries_transient_failure(test_settings, db):
    settings = test_settings.model_copy(
        update={"job_max_attempts": 2, "job_retry_backoff_seconds": 0}
    )
    manager = JobManager(settings, max_workers=1)
    job, _ = manager.create(db, job_type="unit", project_id=None, payload={})
    calls = []
    lock = threading.Lock()

    def flaky(job_db, update):
        with lock:
            calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("transient")
        update(80, "almost_done")
        return {"ok": True}

    manager.submit(db, job, flaky)
    finished = _wait(db, job["id"])
    assert finished["status"] == "succeeded"
    assert finished["attempt_count"] == 2
    assert len(calls) == 2
    manager.close()


def test_duplicate_submit_is_claimed_once(test_settings, db):
    settings = test_settings.model_copy(update={"job_max_attempts": 1})
    manager = JobManager(settings, max_workers=2)
    job, _ = manager.create(db, job_type="unit", project_id=None, payload={})
    calls = []
    lock = threading.Lock()

    def slow(job_db, update):
        with lock:
            calls.append(1)
        time.sleep(0.05)
        return {"ok": True}

    manager.submit(db, job, slow)
    manager.submit(db, job, slow)
    assert _wait(db, job["id"])["status"] == "succeeded"
    assert len(calls) == 1
    manager.close()


def test_prometheus_endpoint(test_settings, db):
    with TestClient(create_app(test_settings)) as client:
        response = client.get("/metrics/prometheus")
        assert response.status_code == 200
        assert "autoresearch_requests_total" in response.text
        assert response.headers["content-type"].startswith("text/plain")
