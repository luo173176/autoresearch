import time

from fastapi.testclient import TestClient

from autoresearch.api.main import create_app


def _wait_for_terminal(client: TestClient, job_id: int) -> dict:
    for _ in range(50):
        body = client.get(f"/jobs/{job_id}").json()
        if body["status"] in {"succeeded", "failed", "cancelled"}:
            return body
        time.sleep(0.02)
    raise AssertionError(f"任务未结束: {body}")


def test_background_literature_job_and_idempotency(test_settings, db, monkeypatch):
    def fake_pipeline(db, settings, **kwargs):
        return {
            "project_id": kwargs["project"]["id"],
            "query": "async",
            "papers_found": 0,
            "papers_new": 0,
            "chunks_created": 0,
            "pdf_downloaded": 0,
            "pdf_parsed": 0,
            "pdf_failed": 0,
            "by_source": {},
            "errors": {},
            "elapsed_ms": 1,
        }

    monkeypatch.setattr("autoresearch.api.routes.run_pipeline", fake_pipeline)
    with TestClient(create_app(test_settings)) as client:
        project = client.post("/projects", json={"name": "async", "question": "q"}).json()
        headers = {"Idempotency-Key": "literature-async-1"}
        response = client.post(
            f"/projects/{project['id']}/literature?background=true",
            headers=headers,
            json={"query": "async", "max_results": 1},
        )
        assert response.status_code == 202, response.text
        accepted = response.json()
        assert accepted["status"] in {"queued", "running"}

        repeated = client.post(
            f"/projects/{project['id']}/literature?background=true",
            headers=headers,
            json={"query": "async", "max_results": 1},
        )
        assert repeated.status_code == 202
        assert repeated.json()["job_id"] == accepted["job_id"]

        finished = _wait_for_terminal(client, accepted["job_id"])
        assert finished["status"] == "succeeded"
        assert finished["output"]["papers_found"] == 0
        assert client.get("/jobs", params={"project_id": project["id"]}).status_code == 200


def test_missing_job_returns_404(test_settings, db):
    with TestClient(create_app(test_settings)) as client:
        assert client.get("/jobs/99999").status_code == 404
        assert client.post("/jobs/99999/cancel").status_code == 404
