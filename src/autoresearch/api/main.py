"""FastAPI 应用工厂。"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import FastAPI

from ..config import Settings, get_settings
from ..db import Database
from ..schemas import HealthOut
from .routes import router


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    app = FastAPI(
        title=settings.app_name,
        version=settings.version,
        description="自主科研与实验平台：文献 → 图谱 → 假设 → 实验 → 报告",
    )
    db = Database(settings)
    app.state.db = db
    app.state.settings = settings

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

    app.include_router(router)
    return app


app = create_app()
