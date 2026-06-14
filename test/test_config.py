import importlib.util
from pathlib import Path

import pytest


def _load_config_module():
    module_path = Path(__file__).resolve().parents[1] / "utils" / "config.py"
    spec = importlib.util.spec_from_file_location("test_config_module", module_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_app_host_defaults_to_loopback(monkeypatch) -> None:
    monkeypatch.delenv("HOST", raising=False)
    config = _load_config_module()

    assert config.app_host() == "127.0.0.1"


def test_project_env_file_points_to_repo_root_dotenv() -> None:
    config = _load_config_module()

    assert config.project_env_file() == Path(__file__).resolve().parents[1] / ".env"


def test_load_project_dotenv_uses_repo_root_dotenv(monkeypatch) -> None:
    config = _load_config_module()
    calls = []

    def fake_load_dotenv(path, *, override=False):
        calls.append((path, override))
        return True

    monkeypatch.setattr(config, "load_dotenv", fake_load_dotenv)

    assert config.load_project_dotenv(override=True) is True
    assert calls == [(config.project_env_file(), True)]


def test_app_host_treats_blank_env_as_default_loopback(monkeypatch) -> None:
    monkeypatch.setenv("HOST", "   ")
    config = _load_config_module()

    assert config.app_host() == "127.0.0.1"


def test_app_port_accepts_valid_env_port(monkeypatch) -> None:
    monkeypatch.setenv("PORT", "8802")
    config = _load_config_module()

    assert config.app_port() == 8802


@pytest.mark.parametrize("port", ["0", "65536", "not-a-number", ""])
def test_app_port_rejects_invalid_env_port(monkeypatch, port: str) -> None:
    monkeypatch.setenv("PORT", port)
    config = _load_config_module()

    with pytest.raises(ValueError, match="PORT must be an integer between 1 and 65535"):
        config.app_port()


def test_upload_dir_expands_user_path(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("UPLOAD_DIR", "~/daiboo-uploads")
    config = _load_config_module()

    assert config.upload_dir() == tmp_path / "daiboo-uploads"


def test_upload_dir_resolves_relative_path_from_project_root(monkeypatch) -> None:
    monkeypatch.setenv("UPLOAD_DIR", "custom_uploads")
    config = _load_config_module()

    assert config.upload_dir() == config.project_root() / "custom_uploads"


def test_upload_dir_treats_blank_env_as_default(monkeypatch) -> None:
    monkeypatch.setenv("UPLOAD_DIR", "   ")
    config = _load_config_module()

    assert config.upload_dir() == config.project_root() / "temp_uploads"
