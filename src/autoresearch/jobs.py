"""后台任务编排：可选异步执行、进度更新、幂等和可查询状态。"""

from __future__ import annotations

import threading
import uuid
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Any, Callable

from loguru import logger

from .config import Settings
from .db import Database

TERMINAL_STATUSES = frozenset({"succeeded", "failed", "cancelled"})
JobFn = Callable[[Database, Callable[[int, str], None]], dict[str, Any]]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class JobManager:
    """轻量级进程内任务管理器。

    M2 先提供无需新增 Redis/Celery 的可靠最小闭环。任务元数据持久化在数据库，
    服务重启后可识别未完成任务；未来可将 submit 实现替换为外部队列而不改 API。
    """

    def __init__(self, settings: Settings, *, max_workers: int = 2):
        self.settings = settings
        self.executor = ThreadPoolExecutor(
            max_workers=max_workers, thread_name_prefix="autoresearch-job"
        )
        self._futures: dict[int, Future[Any]] = {}
        self._lock = threading.Lock()
        self.worker_id = f"worker-{uuid.uuid4().hex[:12]}"

    def close(self) -> None:
        self.executor.shutdown(wait=False, cancel_futures=True)

    def recover(self, db: Database) -> int:
        """将上次进程遗留的未完成任务标记为可诊断的失败状态。"""
        try:
            return db.execute(
                f"UPDATE jobs SET status = {db.ph}, current_step = {db.ph}, "
                f"error = {db.ph}, finished_at = {db.ph} "
                f"WHERE status IN ('queued', 'running')",
                ["failed", "interrupted", "服务重启，中断了未完成任务", _now()],
            )
        except Exception as exc:
            logger.debug("任务恢复跳过（jobs 表尚未迁移）: {}", exc)
            return 0

    def create(
        self,
        db: Database,
        *,
        job_type: str,
        project_id: int | None,
        payload: dict[str, Any],
        idempotency_key: str | None = None,
    ) -> tuple[dict[str, Any], bool]:
        """创建任务；返回 (任务, 是否复用已有任务)。"""
        if idempotency_key:
            existing = db.query_one(
                f"SELECT * FROM jobs WHERE idempotency_key = {db.ph}", [idempotency_key]
            )
            if existing:
                return existing, True
        try:
            job_id = db.insert(
                f"INSERT INTO jobs (project_id, type, input, idempotency_key) "
                f"VALUES ({db.ph}, {db.ph}, {db.ph}, {db.ph})",
                [project_id, job_type, db.dumps(payload), idempotency_key],
            )
        except Exception:
            # 并发重复请求可能先后通过查询；唯一键冲突时返回已存在任务。
            if idempotency_key:
                existing = db.query_one(
                    f"SELECT * FROM jobs WHERE idempotency_key = {db.ph}", [idempotency_key]
                )
                if existing:
                    return existing, True
            raise
        return db.query_one(f"SELECT * FROM jobs WHERE id = {db.ph}", [job_id]), False

    def submit(self, db: Database, job: dict[str, Any], fn: JobFn) -> dict[str, Any]:
        job_id = int(job["id"])
        if job["status"] in TERMINAL_STATUSES:
            return job
        with self._lock:
            future = self._futures.get(job_id)
            if future and not future.done():
                return job
            future = self.executor.submit(self._run, job_id, fn)
            self._futures[job_id] = future
        return db.query_one(f"SELECT * FROM jobs WHERE id = {db.ph}", [job_id]) or job

    def cancel(self, db: Database, job_id: int) -> dict[str, Any] | None:
        job = db.query_one(f"SELECT * FROM jobs WHERE id = {db.ph}", [job_id])
        if not job:
            return None
        with self._lock:
            future = self._futures.get(job_id)
            if job["status"] == "queued" and future and future.cancel():
                self._mark_cancelled(db, job_id, "任务在启动前被取消")
            elif job["status"] == "queued":
                self._mark_cancelled(db, job_id, "任务被取消")
        return db.query_one(f"SELECT * FROM jobs WHERE id = {db.ph}", [job_id])

    def _run(self, job_id: int, fn: JobFn) -> None:
        db = Database(self.settings)
        try:
            db.execute(
                f"UPDATE jobs SET status = {db.ph}, progress = {db.ph}, current_step = {db.ph}, "
                f"started_at = {db.ph}, heartbeat_at = {db.ph}, worker_id = {db.ph}, "
                f"attempt_count = attempt_count + 1 WHERE id = {db.ph} AND status = 'queued'",
                ["running", 1, "starting", _now(), _now(), self.worker_id, job_id],
            )

            def update(progress: int, step: str) -> None:
                db.execute(
                    f"UPDATE jobs SET progress = {db.ph}, current_step = {db.ph} "
                    f", heartbeat_at = {db.ph} WHERE id = {db.ph} AND status = 'running'",
                    [max(0, min(100, int(progress))), step[:200], _now(), job_id],
                )

            result = fn(db, update)
            db.execute(
                f"UPDATE jobs SET status = {db.ph}, progress = 100, current_step = {db.ph}, "
                f"output = {db.ph}, heartbeat_at = {db.ph}, finished_at = {db.ph} "
                f"WHERE id = {db.ph} AND status = 'running'",
                ["succeeded", "completed", db.dumps(result), _now(), _now(), job_id],
            )
        except Exception as exc:
            logger.exception("后台任务 #{} 失败", job_id)
            db.execute(
                f"UPDATE jobs SET status = {db.ph}, current_step = {db.ph}, error = {db.ph}, "
                f"heartbeat_at = {db.ph}, finished_at = {db.ph} "
                f"WHERE id = {db.ph} AND status IN ('queued', 'running')",
                ["failed", "failed", f"{type(exc).__name__}: {exc}"[:4000], _now(), _now(), job_id],
            )

    @staticmethod
    def _mark_cancelled(db: Database, job_id: int, reason: str) -> None:
        db.execute(
            f"UPDATE jobs SET status = {db.ph}, current_step = {db.ph}, error = {db.ph}, "
            f"finished_at = {db.ph} WHERE id = {db.ph} AND status = 'queued'",
            ["cancelled", "cancelled", reason, _now(), job_id],
        )
