"""API 访问控制：默认关闭，配置 API Key 后启用。"""

from __future__ import annotations

import secrets
import hashlib
import threading
import time
from collections import defaultdict, deque

from fastapi import Header, HTTPException, Request


def hash_api_key(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def supplied_api_key(x_api_key: str | None, authorization: str | None) -> str | None:
    if x_api_key:
        return x_api_key.strip()
    if authorization and authorization.lower().startswith("bearer "):
        return authorization[7:].strip()
    return None


def _find_database_key(request: Request, supplied: str) -> dict | None:
    try:
        rows = request.app.state.db.query(
            "SELECT * FROM api_keys WHERE active = TRUE"
            if request.app.state.db.backend == "postgres"
            else "SELECT * FROM api_keys WHERE active = 1"
        )
    except Exception:
        return None
    candidate = hash_api_key(supplied)
    for row in rows:
        if secrets.compare_digest(row["key_hash"], candidate):
            return row
    return None


def require_api_key(
    request: Request,
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
    authorization: str | None = Header(default=None),
) -> None:
    """保护业务路由；健康检查和文档端点不经过该依赖。"""
    expected = request.app.state.settings.api_key.strip()
    supplied = supplied_api_key(x_api_key, authorization)
    if expected and supplied and secrets.compare_digest(supplied, expected):
        request.state.api_key_project_id = request.app.state.settings.api_key_project_id
        request.state.api_key_authenticated = True
        return
    database_key = _find_database_key(request, supplied) if supplied else None
    has_database_keys = False
    try:
        has_database_keys = bool(
            request.app.state.db.scalar(
                "SELECT COUNT(*) FROM api_keys WHERE active = TRUE"
                if request.app.state.db.backend == "postgres"
                else "SELECT COUNT(*) FROM api_keys WHERE active = 1"
            )
        )
    except Exception:
        pass
    if database_key:
        request.state.api_key_project_id = database_key["project_id"]
        request.state.api_key_authenticated = True
        request.state.api_key_rate_limit = database_key["rate_limit_per_minute"]
        return
    if not expected and not has_database_keys:
        request.state.api_key_project_id = None
        return
    if not supplied or (expected and not secrets.compare_digest(supplied, expected)):
        raise HTTPException(
            status_code=401,
            detail="需要有效的 API Key",
            headers={"WWW-Authenticate": "ApiKey"},
        )
    raise HTTPException(status_code=401, detail="需要有效的 API Key")


def require_project_access(request: Request) -> None:
    """当 API Key 绑定项目时，阻止访问其他项目资源。"""
    allowed = getattr(request.state, "api_key_project_id", None)
    if allowed is None:
        allowed = request.app.state.settings.api_key_project_id
    if allowed is None:
        return
    project_id = request.path_params.get("project_id")
    if project_id is None:
        db = request.app.state.db
        if "hypothesis_id" in request.path_params:
            row = db.query_one(
                f"SELECT project_id FROM hypotheses WHERE id = {db.ph}",
                [request.path_params["hypothesis_id"]],
            )
            project_id = row["project_id"] if row else None
        elif "experiment_id" in request.path_params:
            row = db.query_one(
                f"SELECT h.project_id FROM experiments e JOIN hypotheses h ON h.id=e.hypothesis_id "
                f"WHERE e.id = {db.ph}",
                [request.path_params["experiment_id"]],
            )
            project_id = row["project_id"] if row else None
        elif "job_id" in request.path_params:
            row = db.query_one(
                f"SELECT project_id FROM jobs WHERE id = {db.ph}",
                [request.path_params["job_id"]],
            )
            project_id = row["project_id"] if row else None
    if project_id is None:
        return
    if int(project_id) != int(allowed):
        raise HTTPException(status_code=403, detail="当前 API Key 无权访问该项目")


class RateLimiter:
    """轻量进程内滑动窗口限流器；多实例部署应在网关或 Redis 层限流。"""

    def __init__(self, limit: int, window_seconds: float = 60.0):
        self.limit = max(0, int(limit))
        self.window_seconds = window_seconds
        self._events: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def allow(self, key: str) -> bool:
        if self.limit == 0:
            return True
        now = time.monotonic()
        with self._lock:
            events = self._events[key]
            while events and now - events[0] >= self.window_seconds:
                events.popleft()
            if len(events) >= self.limit:
                return False
            events.append(now)
            if len(self._events) > 10000:
                self._events = defaultdict(
                    deque,
                    {
                        k: v
                        for k, v in self._events.items()
                        if v and now - v[-1] < self.window_seconds
                    },
                )
            return True
