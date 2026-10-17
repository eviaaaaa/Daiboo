"""Session-local fast browser tools: RED/GREEN and contract tests."""
import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from tools.browser_runtime import (
    BrowserBatchInput, BrowserStep, build_batch_code, make_browser_runtime_tools,
)


def fake_tool(name, result=None, args=None):
    return SimpleNamespace(name=name, args=args or {}, description=name,
                           ainvoke=AsyncMock(return_value=result))


def test_batch_validates_before_browser_actions():
    with pytest.raises(ValidationError):
        BrowserBatchInput(steps=[])
    with pytest.raises(ValidationError):
        BrowserBatchInput(steps=[{'op': 'evaluate', 'target': 'body'}])
    with pytest.raises(ValidationError):
        BrowserStep(op='fill', target='#name')
    with pytest.raises(ValidationError):
        BrowserBatchInput(steps=[{'op': 'click', 'target': '#x'}] * 13)


def test_batch_code_keeps_user_data_out_of_executable_code():
    value = '\"); process.exit(); // </script> 😀'
    code = build_batch_code([BrowserStep(op='fill', target='#name', value=value)], 800, 2000)
    assert 'JSON.parse(' in code
    assert 'Promise.all' not in code
    assert 'page.screenshot' not in code
    assert 'outerHTML' not in code
    assert 'catch' in code
    assert 'completed' in code


@pytest.mark.asyncio
async def test_batch_uses_one_backend_call_and_caps_result():
    backend = fake_tool('browser_run_code_unsafe', [
        {'type': 'text', 'text': '### Result\n' + json.dumps({'ok': True, 'completed': 2, 'reads': []}) + '\n### Ran Playwright code\n```js\n...\n```'}
    ], {'code': {'type': 'string'}})
    batch = next(t for t in make_browser_runtime_tools([backend]) if t.name == 'browser_batch')
    result = await batch.ainvoke({'steps': [{'op': 'fill', 'target': '#name', 'value': 'Alice'}, {'op': 'click', 'target': '#save'}]})
    assert result['ok'] is True
    assert result['completed'] == 2
    assert backend.ainvoke.await_count == 1
    assert '### Ran Playwright code' not in json.dumps(result)


@pytest.mark.asyncio
async def test_runtime_info_discloses_only_requested_schema():
    tools = [fake_tool('browser_snapshot', args={'target': {}, 'depth': {}}),
             fake_tool('browser_run_code_unsafe', args={'code': {}})]
    info = next(t for t in make_browser_runtime_tools(tools) if t.name == 'browser_runtime_info')
    summary = await info.ainvoke({})
    assert summary['snapshot_options'] == ['depth', 'target']
    assert summary['interactive_snapshot'] is False
    assert 'schemas' not in summary
    details = await info.ainvoke({'tool_names': ['browser_snapshot']})
    assert list(details['schemas']) == ['browser_snapshot']
    assert 'code' not in json.dumps(details['schemas'])


@pytest.mark.asyncio
async def test_batch_missing_backend_is_explicit_and_never_fabricates_success():
    batch = next(t for t in make_browser_runtime_tools([]) if t.name == 'browser_batch')
    result = await batch.ainvoke({'steps': [{'op': 'click', 'target': '#save'}]})
    assert result['ok'] is False
    assert 'unavailable' in result['error']


@pytest.mark.asyncio
async def test_batch_backend_errors_do_not_become_success():
    backend = fake_tool('browser_run_code_unsafe', [{'type': 'text', 'text': '### Error\nError: page closed'}])
    batch = next(t for t in make_browser_runtime_tools([backend]) if t.name == 'browser_batch')
    result = await batch.ainvoke({'steps': [{'op': 'click', 'target': '#save'}]})
    assert result['ok'] is False
    assert 'page closed' not in json.dumps(result)
    assert result['reason'] == 'backend_error'


@pytest.mark.asyncio
async def test_batch_serializes_calls_within_the_session():
    active = 0
    peak = 0
    async def invoke(_):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(.01)
        active -= 1
        return {'ok': True, 'completed': 1, 'reads': []}
    backend = fake_tool('browser_run_code_unsafe')
    backend.ainvoke = invoke
    batch = next(t for t in make_browser_runtime_tools([backend]) if t.name == 'browser_batch')
    args = {'steps': [{'op': 'click', 'target': '#save'}]}
    await asyncio.gather(batch.ainvoke(args), batch.ainvoke(args))
    assert peak == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('kind', ['envelope', 'exception', 'dict', 'json'])
async def test_backend_error_never_echoes_exception_or_call_log(kind):
    secret = 'AuditFakeSecret12345'
    backend = fake_tool('browser_run_code_unsafe', [{'type': 'text', 'text': '### Error\n' + secret}])
    if kind == 'exception':
        backend.ainvoke.side_effect = RuntimeError(secret)
    if kind in {'dict', 'json'}:
        result = {'ok': False, 'error': secret, 'hint': secret}
        backend.ainvoke.return_value = result if kind == 'dict' else json.dumps(result)
    result = await make_browser_runtime_tools([backend])[0].ainvoke({'steps': [{'op': 'read_value', 'target': 'input'}]})
    assert not result['ok']
    assert secret not in json.dumps(result)
    assert result['reason'] == 'backend_error'


@pytest.mark.asyncio
async def test_runtime_schema_keeps_required_and_additional_properties():
    from utils.mcp_client import MCPToolList
    schema = {'type': 'object', 'properties': {'function': {'type': 'string'}},
              'required': ['function'], 'additionalProperties': False,
              'anyOf': [{'required': ['function']}]}
    public = fake_tool('browser_evaluate', args=schema['properties'])
    public.args_schema = schema
    hidden = fake_tool('browser_run_code_unsafe')
    hidden.args_schema = {'type': 'object', 'properties': {'code': {}}}
    tools = MCPToolList([public, hidden], snapshot_mode='none')
    info = make_browser_runtime_tools(tools)[1]
    result = await info.ainvoke({'tool_names': ['browser_evaluate', 'browser_run_code_unsafe']})
    assert result['schemas'] == {'browser_evaluate': schema}
    assert result['unknown_tools'] == ['browser_run_code_unsafe']
