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


@pytest.mark.asyncio
async def test_ensure_browser_running_rejects_invalid_explicit_port(monkeypatch) -> None:
    monkeypatch.setenv("DEBUGGING_PORT", "9222")

    sys.modules.pop("test_my_browser_module", None)
    my_browser = _load_my_browser_module()

    async def fake_check_port_in_use(port: int) -> bool:
        return True

    monkeypatch.setattr(my_browser, "check_port_in_use", fake_check_port_in_use)

    with pytest.raises(ValueError, match="DEBUGGING_PORT must be an integer between 1 and 65535"):
        await my_browser.ensure_browser_running(port=0)


def test_build_browser_command_adds_headless_only_when_requested(monkeypatch) -> None:
    monkeypatch.setenv("BROWSER_HEADLESS", "auto")
    my_browser = _load_my_browser_module()

    headed = my_browser._build_browser_command(9222, headless=False)
    headless = my_browser._build_browser_command(9222, headless=True)

    assert "--headless=new" not in headed
    assert "--headless=new" in headless


@pytest.mark.parametrize("value", ["invalid", "yes-please", "2"])
def test_my_browser_rejects_invalid_headless_mode(monkeypatch, value: str) -> None:
    monkeypatch.setenv("BROWSER_HEADLESS", value)

    with pytest.raises(ValueError, match="BROWSER_HEADLESS must be one of"):
        _load_my_browser_module()


@pytest.mark.asyncio
async def test_linux_auto_mode_retries_headless_after_headed_timeout(monkeypatch) -> None:
    monkeypatch.setenv("BROWSER_HEADLESS", "auto")
    my_browser = _load_my_browser_module()
    launched: list[list[str]] = []

    class FakeProcess:
        def terminate(self):
            return None

        def wait(self, timeout=None):
            return 0

        def kill(self):
            return None

    async def fake_cdp_ready(port: int) -> bool:
        return False

    async def fake_port_in_use(port: int) -> bool:
        return False

    outcomes = iter([False, True])

    async def fake_wait_for_cdp(port: int) -> bool:
        return next(outcomes)

    def fake_popen(command):
        launched.append(command)
        return FakeProcess()

    monkeypatch.setattr(my_browser, "check_cdp_ready", fake_cdp_ready)
    monkeypatch.setattr(my_browser, "check_port_in_use", fake_port_in_use)
    monkeypatch.setattr(my_browser, "_wait_for_cdp", fake_wait_for_cdp)
    monkeypatch.setattr(my_browser.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(my_browser.sys, "platform", "linux")

    await my_browser.ensure_browser_running(9222)

    assert len(launched) == 2
    assert "--headless=new" not in launched[0]
    assert "--headless=new" in launched[1]
    my_browser.cleanup_browser()


@pytest.mark.asyncio
async def test_existing_non_cdp_listener_is_not_accepted(monkeypatch) -> None:
    my_browser = _load_my_browser_module()

    async def fake_port_in_use(port: int) -> bool:
        return True

    async def fake_cdp_ready(port: int) -> bool:
        return False

    monkeypatch.setattr(my_browser, "check_port_in_use", fake_port_in_use)
    monkeypatch.setattr(my_browser, "check_cdp_ready", fake_cdp_ready)

    with pytest.raises(RuntimeError, match="not a Chrome DevTools endpoint"):
        await my_browser.ensure_browser_running(9222)
