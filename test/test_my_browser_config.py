import importlib.util
import sys
from pathlib import Path


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
