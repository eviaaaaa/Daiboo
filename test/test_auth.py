# -*- coding: utf-8 -*-
"""测试 utils/auth.py 认证与限流中间件。"""

import os

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from utils.auth import AuthMiddleware, _check_rate, _window


@pytest.fixture(autouse=True)
def _reset_rate_state() -> None:
    """每个测试前清空限流状态。"""
    _window.clear()
    yield
    _window.clear()


@pytest.fixture
def app_no_auth() -> FastAPI:
    """未配置 API Key 的 app — 所有请求放行。"""
    os.environ.pop("DAIBOO_API_KEY", None)
    app = FastAPI()
    app.add_middleware(AuthMiddleware)

    @app.get("/test")
    async def test_route():
        return {"ok": True}

    return app


@pytest.fixture
def app_with_auth(monkeypatch) -> FastAPI:
    """配置了 API Key 的 app — 需要 X-API-Key header。"""
    monkeypatch.setenv("DAIBOO_API_KEY", "secret123")
    app = FastAPI()
    app.add_middleware(AuthMiddleware)

    @app.get("/test")
    async def test_route():
        return {"ok": True}

    return app


# ── 无认证模式 ─────────────────────────────────────────────────────────────────

def test_no_auth_allows_all(app_no_auth) -> None:
    """未配置 API Key 时，所有请求放行。"""
    client = TestClient(app_no_auth)
    resp = client.get("/test")
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}


def test_no_auth_health_always_allowed(app_no_auth) -> None:
    """/health 始终免鉴权。"""
    app = app_no_auth

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    client = TestClient(app)
    resp = client.get("/health")
    assert resp.status_code == 200


# ── 认证模式 ───────────────────────────────────────────────────────────────────

def test_auth_allows_with_valid_key(app_with_auth) -> None:
    """正确 API Key 的请求通过。"""
    client = TestClient(app_with_auth)
    resp = client.get("/test", headers={"X-API-Key": "secret123"})
    assert resp.status_code == 200


def test_auth_rejects_without_key(app_with_auth) -> None:
    """缺少 API Key 返回 401。"""
    client = TestClient(app_with_auth)
    resp = client.get("/test")
    assert resp.status_code == 401
    assert "api key" in resp.json()["detail"].lower()


def test_auth_rejects_wrong_key(app_with_auth) -> None:
    """错误 API Key 返回 401。"""
    client = TestClient(app_with_auth)
    resp = client.get("/test", headers={"X-API-Key": "wrong"})
    assert resp.status_code == 401


def test_auth_health_bypass(app_with_auth) -> None:
    """/health 始终免鉴权（即使配置了 API Key）。"""
    app = app_with_auth

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    client = TestClient(app)
    resp = client.get("/health")
    assert resp.status_code == 200


def test_auth_vendor_bypass(app_with_auth) -> None:
    """/vendor/* 始终免鉴权。"""
    app = app_with_auth

    @app.get("/vendor/test.js")
    async def vendor():
        return {"ok": True}

    client = TestClient(app)
    resp = client.get("/vendor/test.js")
    assert resp.status_code == 200


# ── 限流 ───────────────────────────────────────────────────────────────────────

def test_rate_limit_allows_under_limit(app_no_auth) -> None:
    """在限制内请求全部放行。"""
    client = TestClient(app_no_auth)
    for _ in range(5):
        resp = client.get("/test")
        assert resp.status_code == 200


def test_rate_limit_blocks_over_limit(monkeypatch, app_no_auth) -> None:
    """超过限制后返回 429。"""
    monkeypatch.setenv("RATE_LIMIT", "3")
    monkeypatch.setenv("RATE_LIMIT_WINDOW", "60")
    app = FastAPI()
    app.add_middleware(AuthMiddleware)

    @app.get("/test")
    async def test_route():
        return {"ok": True}

    client = TestClient(app)
    for i in range(3):
        resp = client.get("/test")
        assert resp.status_code == 200, f"Request {i} should pass"

    resp = client.get("/test")
    assert resp.status_code == 429
    assert "rate limit" in resp.json()["detail"].lower()


def test_rate_limit_zero_disables(monkeypatch, app_no_auth) -> None:
    """RATE_LIMIT=0 关闭限流。"""
    monkeypatch.setenv("RATE_LIMIT", "0")
    app = FastAPI()
    app.add_middleware(AuthMiddleware)

    @app.get("/test")
    async def test_route():
        return {"ok": True}

    client = TestClient(app)
    for _ in range(100):
        resp = client.get("/test")
        assert resp.status_code == 200


def test__check_rate_unit() -> None:
    """_check_rate 函数单元：基本行为。"""
    os.environ.pop("RATE_LIMIT", None)
    assert _check_rate("test_key") is True
    assert _check_rate("test_key") is True


def test_rate_limit_per_ip_isolation(monkeypatch) -> None:
    """不同 IP 各自独立计数。"""
    monkeypatch.setenv("RATE_LIMIT", "2")
    _window.clear()
    assert _check_rate("ip:1.1.1.1") is True
    assert _check_rate("ip:1.1.1.1") is True   # 第 2 次
    assert _check_rate("ip:1.1.1.1") is False  # 第 3 次 → 429
    assert _check_rate("ip:2.2.2.2") is True   # 不同 IP 不受影响
