import runpy
from pathlib import Path


def test_api_module_main_uses_configured_host_and_port(monkeypatch):
    calls = []

    def fake_run(app, *, host, port):
        calls.append((app, host, port))

    monkeypatch.setenv("HOST", "127.0.0.2")
    monkeypatch.setenv("PORT", "8802")
    monkeypatch.setattr("uvicorn.run", fake_run)

    module_path = Path(__file__).resolve().parents[1] / "api.py"
    runpy.run_path(str(module_path), run_name="__main__")

    assert len(calls) == 1
    app, host, port = calls[0]
    assert getattr(app, "title") == "Daiboo API"
    assert host == "127.0.0.2"
    assert port == 8802
