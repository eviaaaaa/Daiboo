# -*- coding: utf-8 -*-
"""NaxusSurf API 认证与限流。

用法
    在 FastAPI app 上添加中间件：
        from utils.auth import AuthMiddleware
        app.add_middleware(AuthMiddleware)

    或手动使用依赖注入（per-route）：
        from utils.auth import require_auth
        @app.get("/protected", dependencies=[Depends(require_auth)])

环境变量
    NAXUSSURF_API_KEY    设置后启用 API Key 认证；不设置则认证关闭（向后兼容）
    RATE_LIMIT           每分钟请求上限（默认 60）；设 0 关闭限流
    RATE_LIMIT_WINDOW    滑动窗口秒数（默认 60）

    绕过认证的路径（始终免鉴权）：
        /health — 健康检查
        / — 前端首页
        /vendor/* — 静态资源
"""

from __future__ import annotations

import os
import time
from collections import defaultdict
from typing import Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse


# ── 配置（延迟读取环境变量，支持运行时 monkeypatch）───────────────────────────

def _get_api_key() -> str | None:
    return (os.getenv("NAXUSSURF_API_KEY") or "").strip() or None


def _get_rate_limit() -> int:
    return int(os.getenv("RATE_LIMIT", "60"))


def _get_rate_window() -> float:
    return float(os.getenv("RATE_LIMIT_WINDOW", "60"))


# 始终免鉴权的路径前缀
_ALWAYS_ALLOW: tuple[str, ...] = ("/health", "/vendor/")

# ── 限流状态（进程内，重启重置）────────────────────────────────────────────────

_window: defaultdict[str, list[float]] = defaultdict(list)


def _clean_window(key: str, now: float) -> None:
    """丢弃窗口外的旧时间戳。"""
    cutoff = now - _get_rate_window()
    bucket = _window[key]
    while bucket and bucket[0] < cutoff:
        bucket.pop(0)


def _check_rate(key: str) -> bool:
    """滑动窗口限流。返回 True 表示通过。"""
    limit = _get_rate_limit()
    if limit <= 0:
        return True
    now = time.time()
    _clean_window(key, now)
    if len(_window[key]) >= limit:
        return False
    _window[key].append(now)
    return True


# ── 认证检查 ───────────────────────────────────────────────────────────────────

def _client_key(request: Request) -> str:
    """提取客户端标识：API Key 优先，否则 IP。"""
    api_key = _get_api_key()
    key = request.headers.get("X-API-Key", "")
    if key and api_key:
        return f"key:{key}"
    # 回退 IP
    forwarded = request.headers.get("X-Forwarded-For")
    ip = (forwarded or "").split(",")[0].strip() or (request.client.host if request.client else "unknown")
    return f"ip:{ip}"


def _is_always_allowed(path: str) -> bool:
    return path == "/" or any(path.startswith(p) for p in _ALWAYS_ALLOW)


# ── 中间件 ────────────────────────────────────────────────────────────────────

class AuthMiddleware(BaseHTTPMiddleware):
    """统一认证 + 限流中间件。

    通过 ASGI 中间件实现，无需 per-route 装饰器。
    认证关闭时（NAXUSSURF_API_KEY 未设置），所有请求直接放行。
    """

    async def dispatch(self, request: Request, call_next: Callable) -> JSONResponse:
        path = request.url.path

        # 始终放行的路径
        if _is_always_allowed(path):
            return await call_next(request)

        # 认证检查（仅当 API Key 已配置）
        api_key = _get_api_key()
        if api_key:
            req_key = request.headers.get("X-API-Key", "")
            if req_key != api_key:
                return JSONResponse(
                    status_code=401,
                    content={"detail": "Invalid or missing API key. Set X-API-Key header."},
                )

        # 限流检查
        ckey = _client_key(request)
        if not _check_rate(ckey):
            return JSONResponse(
                status_code=429,
                content={
                    "detail": (
                        f"Rate limit exceeded "
                        f"({_get_rate_limit()} req/{_get_rate_window():.0f}s). "
                        "Retry later."
                    )
                },
            )

        return await call_next(request)
