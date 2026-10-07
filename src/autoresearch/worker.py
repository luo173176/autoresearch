"""独立任务 worker：从数据库队列读取任务并重建业务 handler。"""

from __future__ import annotations

import time
from typing import Any

from loguru import logger

from .config import Settings
from .db import Database
from .experiments import run_experiment
from .graph import build_graph
from .hypotheses import generate_hypotheses
from .jobs import JobManager, JobFn
from .literature import run_pipeline
from .reporting import generate_report
from .research import run_framework_research
from .schemas import (
    GraphBuildRequest,
    HypothesisGenerateRequest,
    LiteratureRequest,
    ResearchRequest,
)


def _literature(db, settings, project, payload, update):
    update(10, "searching")
    result = run_pipeline(
        db,
        settings,
        project=project,
        query=payload.query,
        sources=payload.sources,
        max_results=payload.max_results,
        download_pdfs=payload.download_pdfs,
        pdf_limit=payload.pdf_limit,
        use_llm=payload.use_llm,
    )
    update(100, "literature_completed")
    return result


def _graph(db, settings, project_id, payload, update):
    update(10, "extracting_graph")
    result = build_graph(db, settings, project_id=project_id, use_llm=payload.use_llm)
    update(100, "graph_completed")
    return result


def _hypotheses(db, settings, project_id, payload, update):
    update(10, "generating_hypotheses")
    result = generate_hypotheses(
        db,
        settings,
        project_id=project_id,
        max_hypotheses=payload.max_hypotheses,
        use_llm=payload.use_llm,
    )
    update(100, "hypotheses_completed")
    return result


def _experiment(db, settings, experiment_id, update):
    update(10, "running_experiment")
    result = run_experiment(db, settings, experiment_id=experiment_id)
    update(100, "experiment_completed")
    return result


def _report(db, settings, project_id, update):
    update(10, "generating_report")
    result = generate_report(db, settings, project_id=project_id)
    update(100, "report_completed")
    return result


def _research(db, settings, project_id, payload, update):
    update(10, "researching_framework")
    result = run_framework_research(
        db,
        settings,
        project_id=project_id,
        mode=payload.mode,
        framework=payload.framework,
        paper_ids=payload.paper_ids,
        use_llm=payload.use_llm,
        max_chunks=payload.max_chunks,
        query=payload.query,
        sources=payload.sources,
        max_results=payload.max_results,
        download_pdfs=payload.download_pdfs,
        pdf_limit=payload.pdf_limit,
    )
    update(100, "research_completed")
    return result


def handler_for_job(db: Database, settings: Settings, job: dict[str, Any]) -> JobFn:
    """根据持久化的任务类型和 input 重建 handler，不执行任意数据库代码。"""
    payload = job.get("input") or {}
    job_type = job["type"]
    if job_type == "literature":
        project_id = int(payload["project_id"])
        project = db.query_one(f"SELECT * FROM projects WHERE id = {db.ph}", [project_id])
        if project is None:
            raise LookupError(f"任务所属项目不存在: {project_id}")
        data = LiteratureRequest.model_validate(payload)
        return lambda task_db, update: _literature(task_db, settings, project, data, update)
    if job_type == "graph":
        data = GraphBuildRequest.model_validate(payload)
        return lambda task_db, update: _graph(
            task_db, settings, int(payload["project_id"]), data, update
        )
    if job_type == "hypotheses":
        data = HypothesisGenerateRequest.model_validate(payload)
        return lambda task_db, update: _hypotheses(
            task_db, settings, int(payload["project_id"]), data, update
        )
    if job_type == "experiment_run":
        experiment_id = int(payload["experiment_id"])
        return lambda task_db, update: _experiment(task_db, settings, experiment_id, update)
    if job_type == "report":
        project_id = int(payload["project_id"])
        return lambda task_db, update: _report(task_db, settings, project_id, update)
    if job_type == "research":
        data = ResearchRequest.model_validate(payload)
        return lambda task_db, update: _research(
            task_db, settings, int(payload["project_id"]), data, update
        )
    raise ValueError(f"不支持的任务类型: {job_type}")


def dispatch_pending(
    manager: JobManager, db: Database, settings: Settings, *, limit: int = 20
) -> int:
    """扫描并提交 queued 任务；真正执行仍由 JobManager 原子抢占。"""
    rows = db.query(
        f"SELECT * FROM jobs WHERE status = 'queued' ORDER BY priority DESC, id ASC LIMIT {db.ph}",
        [limit],
    )
    submitted = 0
    for job in rows:
        try:
            fn = handler_for_job(db, settings, job)
            manager.submit(db, job, fn)
            submitted += 1
        except Exception as exc:
            logger.exception("无法构建任务 #{} handler", job["id"])
            db.execute(
                f"UPDATE jobs SET status = {db.ph}, current_step = {db.ph}, error = {db.ph}, "
                f"finished_at = {db.ph} WHERE id = {db.ph} AND status = 'queued'",
                [
                    "failed",
                    "handler_error",
                    f"{type(exc).__name__}: {exc}"[:4000],
                    _now(),
                    job["id"],
                ],
            )
    return submitted


def _now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


def run_worker(
    settings: Settings | None = None,
    *,
    interval: float = 1.0,
    once: bool = False,
    max_workers: int | None = None,
    batch_size: int = 20,
) -> int:
    """运行独立 worker；once 模式用于部署探针、测试和一次性 drain。"""
    settings = settings or Settings()
    settings.ensure_dirs()
    db = Database(settings)
    db.migrate()
    manager = JobManager(settings, max_workers=max_workers or settings.job_max_workers)
    print(f"[worker] started id={manager.worker_id} backend={db.backend}")
    try:
        while True:
            dispatch_pending(manager, db, settings, limit=batch_size)
            if once:
                time.sleep(max(0.05, interval))
                remaining = db.scalar(
                    "SELECT COUNT(*) FROM jobs WHERE status IN ('queued', 'running')"
                )
                if not remaining:
                    return 0
            else:
                time.sleep(max(0.05, interval))
    except KeyboardInterrupt:
        print("[worker] stopping")
        return 0
    finally:
        manager.close()
