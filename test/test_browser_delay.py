from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from tools.delay_tool_call import delay_tool_call


@pytest.mark.asyncio
async def test_native_auto_wait_has_no_unconditional_delay(monkeypatch):
    import importlib
    module = importlib.import_module("tools.delay_tool_call")
    sleep = AsyncMock()
    monkeypatch.setattr(module.asyncio, "sleep", sleep)
    monkeypatch.delenv("BROWSER_ACTION_DELAY_MS", raising=False)
    handler = AsyncMock(return_value="real-handler-result")
    result = await delay_tool_call.awrap_tool_call(SimpleNamespace(tool=SimpleNamespace(name="browser_batch")), handler)
    assert result == "real-handler-result"
    sleep.assert_not_awaited()
    handler.assert_awaited_once()


@pytest.mark.asyncio
async def test_optional_delay_is_bounded_and_browser_only(monkeypatch):
    import importlib
    module = importlib.import_module("tools.delay_tool_call")
    sleep = AsyncMock()
    monkeypatch.setattr(module.asyncio, "sleep", sleep)
    monkeypatch.setenv("BROWSER_ACTION_DELAY_MS", "125")
    handler = AsyncMock(return_value="ok")
    await delay_tool_call.awrap_tool_call(SimpleNamespace(tool=SimpleNamespace(name="browser_click")), handler)
    sleep.assert_awaited_once_with(0.125)
    sleep.reset_mock()
    await delay_tool_call.awrap_tool_call(SimpleNamespace(tool=SimpleNamespace(name="list_skills")), handler)
    sleep.assert_not_awaited()
    monkeypatch.setenv("BROWSER_ACTION_DELAY_MS", "-1")
    with pytest.raises(ValueError, match="BROWSER_ACTION_DELAY_MS"):
        await delay_tool_call.awrap_tool_call(SimpleNamespace(tool=SimpleNamespace(name="browser_click")), handler)
