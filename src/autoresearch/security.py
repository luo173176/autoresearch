"""API 访问控制：默认关闭，配置 API Key 后启用。"""

from __future__ import annotations

import secrets
import threading
import time
from collections import defaultdict, deque

from fastapi import Header, HTTPException, Request


def require_api_key(
    request: Request,
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
    authorization: str | None = Header(default=None),
) -> None:
    """保护业务路由；健康检查和文档端点不经过该依赖。"""
    expected = request.app.state.settings.api_key.strip()
    if not expected:
        return
    supplied = x_api_key
    if not supplied and authorization and authorization.lower().startswith("bearer "):
        supplied = authorization[7:].strip()
    if not supplied or not secrets.compare_digest(supplied, expected):
        raise HTTPException(
            status_code=401,
            detail="需要有效的 API Key",
            headers={"WWW-Authenticate": "ApiKey"},
        )
    request.state.api_key_authenticated = bool(expected)


def require_project_access(request: Request) -> None:
    """当 API Key 绑定项目时，阻止访问其他项目资源。"""
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
