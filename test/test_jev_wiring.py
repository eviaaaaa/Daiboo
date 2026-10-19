"""Actual agent wiring, schema disclosure and session cleanup for opt-in Jev."""
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from langchain_core.tools import StructuredTool

from tools.browser_runtime import make_browser_runtime_tools
from utils.mcp_client import MCPToolList


def named_tool(name):
    return StructuredTool.from_function(lambda: 'unused', name=name, description='fixture',
                                        metadata={'jev_model': 'jev-latest'})


@pytest.mark.asyncio
@pytest.mark.parametrize('raise_inside', [False, True])
async def test_session_closes_jev_resources_before_mcp(raise_inside, monkeypatch):
    import utils.mcp_client as module
    order = []
    @asynccontextmanager
    async def session(_):
        try:
            yield SimpleNamespace(initialize=AsyncMock())
        finally:
            order.append('mcp_closed')
    monkeypatch.setattr(module, 'create_session', session)
    monkeypatch.setattr(module, 'load_mcp_tools', AsyncMock(return_value=[]))
    async def close_client():
        order.append('jev_closed')
    try:
        async with module.create_persistent_mcp_session('http://127.0.0.1:1') as tools:
            tools.resources.push_async_callback(close_client)
            if raise_inside:
                raise RuntimeError('fixture')
    except RuntimeError:
        assert raise_inside
    assert order == ['jev_closed', 'mcp_closed']


@pytest.mark.asyncio
async def test_runtime_discloses_real_jev_schema_without_calling_it():
    native = MCPToolList([], snapshot_mode='none')
    extra = [named_tool('browser_jev_decide'), named_tool('browser_jev_run')]
    info = make_browser_runtime_tools(native, additional_tools=extra)[1]
    data = await info.ainvoke({'tool_names': ['browser_jev_run', 'browser_run_code_unsafe']})
    assert data['jev'] == {'configured': True, 'model': 'jev-latest', 'endpoint_support': 'not_probed'}
    assert 'browser_jev_decide' in data['tool_names']
    assert data['schemas']['browser_jev_run'] == extra[1].args_schema.model_json_schema()
    assert data['unknown_tools'] == ['browser_run_code_unsafe']


@pytest.mark.asyncio
async def test_runtime_when_jev_disabled_has_no_extra_schema_or_claim():
    data = await make_browser_runtime_tools(MCPToolList([], snapshot_mode='none'))[1].ainvoke({})
    assert data['jev']['configured'] is False
    assert not any(name.startswith('browser_jev') for name in data['tool_names'])


def test_jev_tools_are_resident_only_if_actually_registered():
    from test.test_browser_disclosure import _capture, _request
    from utils.browser_disclosure import BrowserDisclosureMiddleware
    tools = [named_tool('browser_click'), named_tool('browser_runtime_info'),
             named_tool('browser_jev_decide'), named_tool('browser_jev_run')]
    selected = _capture(BrowserDisclosureMiddleware(), _request(tools=tools))
    assert [t.name for t in selected.tools] == ['browser_runtime_info', 'browser_jev_decide', 'browser_jev_run']


def test_factory_registers_and_discloses_the_same_jev_tools(monkeypatch):
    import utils.agent_factory as module
    extra = [named_tool('browser_jev_decide'), named_tool('browser_jev_run')]
    monkeypatch.setattr(module, 'make_jev_browser_tools', lambda tools: extra)
    native = MCPToolList([], snapshot_mode='none')
    tools = module.get_agent_tools(native)
    assert [t for t in tools if t.name.startswith('browser_jev')] == extra
    info = next(t for t in tools if t.name == 'browser_runtime_info')
    assert info is not None
