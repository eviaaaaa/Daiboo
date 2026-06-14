"""Tests for the /health endpoint."""

from pathlib import Path


def test_health_endpoint_exists_in_api():
    api = (Path(__file__).resolve().parents[1] / "api.py").read_text(encoding="utf-8")
    assert '"/health"' in api or "'/health'" in api
    assert "health_check" in api
    assert "HealthResponse" in api
    assert "tools_loaded" in api
    assert "agent_ready" in api


def test_health_response_model_defined():
    api = (Path(__file__).resolve().parents[1] / "api.py").read_text(encoding="utf-8")
    assert "class HealthResponse" in api
    assert "status: str" in api
    assert "tools_loaded: bool" in api
    assert "agent_ready: bool" in api
