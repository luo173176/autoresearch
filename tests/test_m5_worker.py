import time

from autoresearch.jobs import JobManager
from autoresearch.worker import dispatch_pending


def test_independent_worker_dispatches_persisted_literature_job(test_settings, db, monkeypatch):
    project_id = db.insert(
        f"INSERT INTO projects (name, question) VALUES ({db.ph}, {db.ph})",
        ["worker", "q"],
    )
    manager = JobManager(test_settings.model_copy(update={"job_max_attempts": 1}), max_workers=1)
    job, _ = manager.create(
        db,
        job_type="literature",
        project_id=project_id,
        payload={"project_id": project_id, "query": "q", "max_results": 1},
    )

    monkeypatch.setattr(
        "autoresearch.worker.run_pipeline",
        lambda *args, **kwargs: {
            "project_id": kwargs["project"]["id"],
            "papers_found": 0,
            "papers_new": 0,
            "chunks_created": 0,
            "pdf_downloaded": 0,
            "pdf_parsed": 0,
            "pdf_failed": 0,
            "by_source": {},
            "errors": {},
            "query": "q",
            "elapsed_ms": 1,
        },
    )
    assert dispatch_pending(manager, db, test_settings, limit=5) == 1
    for _ in range(50):
        row = db.query_one(f"SELECT * FROM jobs WHERE id = {db.ph}", [job["id"]])
        if row["status"] == "succeeded":
            break
        time.sleep(0.02)
    assert row["status"] == "succeeded"
    manager.close()
