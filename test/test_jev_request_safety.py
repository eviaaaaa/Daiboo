"""Cancellation must not release the gate before a submitted RPC settles."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from tools.jev_browser import JevRunInput, make_jev_browser_tools
from test.test_jev_browser import FakeBackend, answer, candidate, run_args, session


@pytest.mark.parametrize('op', ['click', 'check'])
@pytest.mark.parametrize('value', ['', 'ignored-one', 'ignored-two'])
def test_unused_values_cannot_create_replay_aliases(op, value):
    with pytest.raises(ValidationError):
        JevRunInput.model_validate(run_args(candidates=[candidate('a', op=op, value=value)]))


@pytest.mark.asyncio
async def test_cancel_drains_submitted_rpc_before_cleanup_and_unlock(monkeypatch):
    import utils.typesafe_client as module
    client = SimpleNamespace(model='test-fake', evaluate=AsyncMock(return_value=answer()), aclose=AsyncMock())
    monkeypatch.setattr(module, 'jev_enabled', lambda: True)
    monkeypatch.setattr(module.JevClient, 'from_env', lambda: client)
    backend = FakeBackend()
    original = backend.ainvoke
    entered, release, settled = asyncio.Event(), asyncio.Event(), asyncio.Event()
    async def delayed(args):
        if '"execute"' in args['code'].replace('\\"', '"'):
            entered.set()
            try:
                await release.wait()
                return await original(args)
            finally:
                settled.set()
        return await original(args)
    backend.ainvoke = delayed
    tools = session(backend)
    helper = make_jev_browser_tools(tools)[1]
    task = asyncio.create_task(helper.ainvoke(run_args(max_actions=1)))
    await asyncio.wait_for(entered.wait(), 2)
    task.cancel()
    await asyncio.sleep(.03)
    try:
        assert not task.done(), 'Cancellation returned while a write RPC was still alive'
        assert tools.session_gate._owner is not None, 'Session gate released before RPC settled'
        assert backend.calls[-1]['phase'] != 'cleanup'
    finally:
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        await tools.resources.aclose()
    assert settled.is_set()
    assert tools.session_gate._owner is None
    assert backend.calls[-1]['phase'] == 'cleanup'
    assert backend.executions == ['go']  # Submitted action may complete; never claimed rolled back.
