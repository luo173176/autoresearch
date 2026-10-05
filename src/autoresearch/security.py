"""API 访问控制：默认关闭，配置 API Key 后启用。"""

from __future__ import annotations

import secrets

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
