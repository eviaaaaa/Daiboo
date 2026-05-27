import importlib.util
import sys
from pathlib import Path

import pytest

def _load_my_browser_module():
    module_path = Path(__file__).resolve().parents[1] / "utils" / "my_browser.py"
    spec = importlib.util.spec_from_file_location("test_my_browser_module", module_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_my_browser_reads_environment_after_dotenv_load(monkeypatch) -> None:
    monkeypatch.setenv("BROWSER_PATH", r"D:\Custom\Browser\browser.exe")
    monkeypatch.setenv("USER_DATA_DIR", r"D:\Custom\UserData")
    monkeypatch.setenv("DEBUGGING_PORT", "9333")

    sys.modules.pop("test_my_browser_module", None)
    my_browser = _load_my_browser_module()

    assert my_browser.BROWSER_PATH == r"D:\Custom\Browser\browser.exe"
    assert my_browser.USER_DATA_DIR == Path(r"D:\Custom\UserData")
    assert my_browser.DEBUGGING_PORT == 9333


def test_my_browser_treats_blank_user_data_dir_as_default(monkeypatch) -> None:
    monkeypatch.setenv("USER_DATA_DIR", "   ")

    sys.modules.pop("test_my_browser_module", None)
    my_browser = _load_my_browser_module()

    assert my_browser.USER_DATA_DIR == Path(r"C:\playwright_edge_refined")


def test_my_browser_resolves_relative_user_data_dir_from_project_root(monkeypatch) -> None:
    monkeypatch.setenv("USER_DATA_DIR", ".browser-profile")

    sys.modules.pop("test_my_browser_module", None)
    my_browser = _load_my_browser_module()

    assert my_browser.USER_DATA_DIR == Path(__file__).resolve().parents[1] / ".browser-profile"


def test_my_browser_treats_blank_debugging_port_as_default(monkeypatch) -> None:
    monkeypatch.setenv("DEBUGGING_PORT", "   ")

    sys.modules.pop("test_my_browser_module", None)
    my_browser = _load_my_browser_module()

    assert my_browser.DEBUGGING_PORT == 9222


@pytest.mark.parametrize("port", ["0", "65536", "not-a-number"])
def test_my_browser_rejects_invalid_debugging_port(monkeypatch, port: str) -> None:
    monkeypatch.setenv("DEBUGGING_PORT", port)

    sys.modules.pop("test_my_browser_module", None)
    with pytest.raises(ValueError, match="DEBUGGING_PORT must be an integer between 1 and 65535"):
        _load_my_browser_module()
