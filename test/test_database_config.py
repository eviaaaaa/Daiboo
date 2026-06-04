import importlib.util
from pathlib import Path


def _load_database_module(monkeypatch, *, env_file: str | None = None, cwd: Path | None = None):
    module_path = Path(__file__).resolve().parents[1] / "database" / "postgresql_database.py"
    calls = []

    import dotenv

    def fake_load_dotenv(*, dotenv_path):
        calls.append(dotenv_path)
        return True

    if cwd is not None:
        monkeypatch.chdir(cwd)
    monkeypatch.setattr(dotenv, "load_dotenv", fake_load_dotenv)
    if env_file is None:
        monkeypatch.delenv("NEXUSSURF_ENV_FILE", raising=False)
    else:
        monkeypatch.setenv("NEXUSSURF_ENV_FILE", env_file)

    spec = importlib.util.spec_from_file_location("test_postgresql_database_module", module_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module, calls


def test_database_dotenv_defaults_to_project_root(monkeypatch, tmp_path) -> None:
    _, calls = _load_database_module(monkeypatch, cwd=tmp_path)

    assert calls == [Path(__file__).resolve().parents[1] / ".env"]


def test_database_dotenv_allows_explicit_env_file_override(monkeypatch, tmp_path) -> None:
    env_file = tmp_path / "custom.env"

    _, calls = _load_database_module(monkeypatch, env_file=str(env_file))

    assert calls == [str(env_file)]
