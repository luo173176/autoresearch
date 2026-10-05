"""FastAPI 应用工厂。"""

from __future__ import annotations

import threading
import time
import uuid
from datetime import datetime, timezone

from fastapi import Depends, FastAPI, Request, Response
from loguru import logger

from ..config import Settings, get_settings
from ..db import Database
from ..jobs import JobManager
from ..schemas import HealthOut
from ..security import require_api_key
from .routes import router


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    app = FastAPI(
        title=settings.app_name,
        version=settings.version,
        description="自主科研与实验平台：文献 → 图谱 → 假设 → 实验 → 报告",
    )
    db = Database(settings)
    jobs = JobManager(settings, max_workers=settings.job_max_workers)
    app.state.db = db
    app.state.settings = settings
    app.state.jobs = jobs
    recovered = jobs.recover(db)
    if recovered:
        logger.warning("recovered {} interrupted background jobs", recovered)
    app.state.metrics = {"requests_total": 0, "requests_failed": 0, "jobs_submitted": 0}
    app.state.metrics_lock = threading.Lock()

    @app.middleware("http")
    async def request_observability(request: Request, call_next):
        request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex
        started = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            with app.state.metrics_lock:
                app.state.metrics["requests_failed"] += 1
            logger.exception("request failed request_id={} path={}", request_id, request.url.path)
            raise
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        with app.state.metrics_lock:
            app.state.metrics["requests_total"] += 1
            if response.status_code >= 500:
                app.state.metrics["requests_failed"] += 1
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Process-Time-ms"] = str(elapsed_ms)
        logger.info(
            "request request_id={} method={} path={} status={} elapsed_ms={}",
            request_id,
            request.method,
            request.url.path,
            response.status_code,
            elapsed_ms,
        )
        return response

    @app.on_event("shutdown")
    def shutdown_jobs() -> None:
        jobs.close()

    @app.get("/health", response_model=HealthOut, tags=["meta"])
    def health() -> HealthOut:
        ok = db.healthy()
        return HealthOut(
            status="ok" if ok else "degraded",
            app=settings.app_name,
            version=settings.version,
            backend=db.backend,
            database=ok,
            time=datetime.now(timezone.utc),
        )

    @app.get("/metrics", dependencies=[Depends(require_api_key)], tags=["meta"])
    def metrics() -> dict:
        with app.state.metrics_lock:
            values = dict(app.state.metrics)
        try:
            values["jobs_active"] = db.scalar(
                "SELECT COUNT(*) FROM jobs WHERE status IN ('queued', 'running')"
            )
        except Exception:
            values["jobs_active"] = 0
        return values

    @app.get("/metrics/prometheus", dependencies=[Depends(require_api_key)], tags=["meta"])
    def metrics_prometheus() -> Response:
        with app.state.metrics_lock:
            values = dict(app.state.metrics)
        try:
            values["jobs_active"] = db.scalar(
                "SELECT COUNT(*) FROM jobs WHERE status IN ('queued', 'running')"
            )
        except Exception:
            values["jobs_active"] = 0
        body = (
            "\n".join(f"autoresearch_{key} {int(value)}" for key, value in sorted(values.items()))
            + "\n"
        )
        return Response(content=body, media_type="text/plain; version=0.0.4")

    app.include_router(router)
    return app


app = create_app()
