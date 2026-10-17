"""Session gate contracts, using real StructuredTool task boundaries."""
import asyncio
from types import SimpleNamespace

import pytest
from langchain_core.messages import ToolMessage
from langchain_core.tools import StructuredTool

from utils.mcp_client import MCPToolList
from tools.browser_runtime import make_browser_runtime_tools


@pytest.mark.asyncio
async def test_atomic_tools_and_batch_share_gate_without_nested_deadlock():
    events = []
    started = asyncio.Event()
    release = asyncio.Event()

    async def backend(code: str):
        events.append('batch-start')
        started.set()
        await release.wait()
        events.append('batch-end')
        return {'ok': True, 'completed': 1, 'reads': []}

    async def atomic(value: str):
        events.append(value)
        await asyncio.sleep(0)
        return value

    tools = MCPToolList([
        StructuredTool.from_function(coroutine=backend, name='browser_run_code_unsafe', description='backend'),
        StructuredTool.from_function(coroutine=atomic, name='browser_navigate', description='atomic'),
    ], snapshot_mode='none')
    batch = make_browser_runtime_tools(tools)[0]
    first = asyncio.create_task(batch.ainvoke({'steps': [{'op': 'click', 'target': '#x'}]}))
    await asyncio.wait_for(started.wait(), 1)
    second = asyncio.create_task(tools[0].ainvoke({'value': 'atomic'}))
    await asyncio.sleep(.02)
    assert events == ['batch-start']
    release.set()
    await asyncio.wait_for(asyncio.gather(first, second), 1)
    assert events == ['batch-start', 'batch-end', 'atomic']


@pytest.mark.asyncio
async def test_parallel_atomic_roots_never_inherit_one_ownership_token():
    active = peak = 0

    async def atomic(value: str):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(.01)
        active -= 1
        return value

    tools = MCPToolList([StructuredTool.from_function(coroutine=atomic, name='browser_evaluate', description='atomic')], snapshot_mode='none')
    await asyncio.gather(*(tools[0].ainvoke({'value': str(i)}) for i in range(5)))
    assert peak == 1


@pytest.mark.asyncio
async def test_diff_observe_action_observe_is_one_gate_region(monkeypatch):
    import loggers.diff_middleware as mod
    events = []
    sampled = asyncio.Event()
    release = asyncio.Event()

    async def evaluate(function: str):
        return ''

    async def click(target: str):
        events.append(target)
        return target

    tools = MCPToolList([
        StructuredTool.from_function(coroutine=evaluate, name='browser_evaluate', description='eval'),
        StructuredTool.from_function(coroutine=click, name='browser_click', description='click'),
    ], snapshot_mode='none')
    count = 0

    async def observe(*args, **kwargs):
        nonlocal count
        count += 1
        events.append('before' if count == 1 else 'after')
        if count == 1:
            sampled.set()
            await release.wait()
        return '<p>safe</p>'

    async def monitor(*args, **kwargs):
        return []

    monkeypatch.setattr(mod, 'observe_simplified', observe)
    monkeypatch.setattr(mod, 'start_transient_monitor', monitor)
    monkeypatch.setattr(mod, 'stop_transient_monitor', monitor)
    middleware = mod.make_diff_middleware(tools)

    async def handler(_):
        await tools[1].ainvoke({'target': 'action'})
        return ToolMessage(content='ok', tool_call_id='gate')

    first = asyncio.create_task(middleware.awrap_tool_call(SimpleNamespace(tool=tools[1]), handler))
    await asyncio.wait_for(sampled.wait(), 1)
    second = asyncio.create_task(tools[1].ainvoke({'target': 'outsider'}))
    await asyncio.sleep(.02)
    assert events == ['before']
    release.set()
    await asyncio.wait_for(asyncio.gather(first, second), 1)
    assert events == ['before', 'action', 'after', 'outsider']


@pytest.mark.asyncio
async def test_cancelled_owner_releases_gate_and_stale_child_cannot_reenter():
    from utils.mcp_client import BrowserSessionGate
    gate = BrowserSessionGate()
    child_ready = asyncio.Event()
    run_child = asyncio.Event()
    child_entered = asyncio.Event()

    async def stale_child():
        child_ready.set()
        await run_child.wait()
        async with gate.hold():
            child_entered.set()

    async with gate.hold():
        child = asyncio.create_task(stale_child())
        await child_ready.wait()
    # Child inherited a previous operation's token; it must not bypass a new
    # owner merely because its ContextVar is non-empty.
    async with gate.hold():
        run_child.set()
        await asyncio.sleep(.02)
        assert not child_entered.is_set()
    await asyncio.wait_for(child, 1)
    assert child_entered.is_set()

    owned = asyncio.Event()
    async def cancelled_owner():
        async with gate.hold():
            owned.set()
            await asyncio.Event().wait()
    owner = asyncio.create_task(cancelled_owner())
    await owned.wait()
    owner.cancel()
    with pytest.raises(asyncio.CancelledError):
        await owner
    async with asyncio.timeout(1):
        async with gate.hold():
            assert gate._owner is not None
