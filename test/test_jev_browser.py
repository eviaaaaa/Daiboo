"""Jev orchestration tests use an explicit fake API, never external inference.

The opt-in live tests exercise the exact fixed JS on isolated Chromium/MCP.
"""
import asyncio
from contextlib import AsyncExitStack
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from tools.jev_browser import JevCandidate, JevRunInput, make_jev_browser_tools
from utils.mcp_client import BrowserSessionGate


def candidate(id='go', target='#go', op='click', **extra):
    return {'id': id, 'description': 'Previously authorized local fixture action',
            'action': {'op': op, 'target': target, **extra}}


def run_args(**extra):
    return {'goal': 'Set the local status to Saved', 'candidates': [candidate()],
            'success_checks': [{'target': '#status', 'text': 'Saved', 'match': 'exact'}], **extra}


def answer(choice='go', probability=.99, confidence=.98, done=.01, options=None):
    options = options or ['go', 'observe_again', 'handoff']
    probabilities = {key: (1-probability)/(len(options)-1) for key in options}
    probabilities[choice] = probability
    return {'ok': True, 'model': 'unit-test-fake', 'usage': {'input_tokens': 1},
            'answers': {'next_action': {'type': 'choice', 'choice': choice,
                                      'probabilities': probabilities, 'confidence': confidence},
                        'goal_done': {'type': 'noul', 'noul': done}}}


class FakeBackend:
    name = 'browser_run_code_unsafe'
    def __init__(self):
        self.calls = []
        self.executions = []
        self.saved = False
        self.fail_execute = False
    async def ainvoke(self, args):
        # The first line embeds JSON data; no caller values are executable JS.
        cfg = json.loads(json.loads(args['code'].split('JSON.parse(', 1)[1].split(');', 1)[0]))
        self.calls.append(cfg)
        if cfg['phase'] == 'prepare':
            return {'ok': True, 'page_text': 'Local form', 'truncated': False,
                    'eligible_ids': [c['id'] for c in cfg['candidates']],
                    'candidate_status': [], 'checks': [self.saved]}
        if cfg['phase'] == 'execute':
            self.executions.append(cfg['candidate_id'])
            if self.fail_execute:
                return {'ok': False, 'reason': 'action_failed', 'error': 'FAKE_SECRET Call log'}
            self.saved = True
            return {'ok': True, 'completed': 1}
        if cfg['phase'] == 'verify':
            return {'ok': True, 'checks': [self.saved]}
        return {'ok': True}


@pytest.fixture
def enabled(monkeypatch):
    import utils.typesafe_client as client_module
    monkeypatch.setattr(client_module, 'jev_enabled', lambda: True)
    client = SimpleNamespace(model='jev-latest', evaluate=AsyncMock(return_value=answer()), aclose=AsyncMock())
    monkeypatch.setattr(client_module.JevClient, 'from_env', lambda: client)
    return client


def session(backend):
    return SimpleNamespace(all_tools={backend.name: backend}, session_gate=BrowserSessionGate(),
                           resources=AsyncExitStack())


def test_candidates_and_budget_are_closed_sets():
    for invalid in [candidate(id='handoff'), candidate(id='observe_again'),
                    candidate(op='read_text'), candidate(op='wait_for')]:
        with pytest.raises(ValidationError):
            JevCandidate.model_validate(invalid)
    for changes in [{'candidates': [candidate(), candidate()]}, {'success_checks': []},
                    {'max_actions': 13}, {'candidates': [candidate(str(i)) for i in range(13)]},
                    {'candidates': [candidate('a'), candidate('b')]}]:
        with pytest.raises(ValidationError):
            JevRunInput.model_validate(run_args(**changes))


def test_disabled_does_not_construct_client_or_touch_browser(monkeypatch):
    import utils.typesafe_client as client_module
    monkeypatch.setattr(client_module, 'jev_enabled', lambda: False)
    monkeypatch.setattr(client_module.JevClient, 'from_env', lambda: pytest.fail('credential read'))
    assert make_jev_browser_tools(None) == []


@pytest.mark.asyncio
async def test_run_independent_checks_and_client_session_reuse(enabled):
    backend = FakeBackend(); tools = session(backend)
    enabled.evaluate.side_effect = [answer(), answer(choice='handoff', done=.99,
        options=['handoff', 'observe_again'])]
    helpers = {t.name: t for t in make_jev_browser_tools(tools)}
    result = await helpers['browser_jev_run'].ainvoke(run_args())
    assert result['verified'] and result['executed'] and result['completed_ids'] == ['go']
    assert backend.executions == ['go']
    assert enabled.evaluate.await_count == 2
    first = enabled.evaluate.call_args_list[0].kwargs
    assert set(first['questions']) == {'goal_done', 'next_action'}
    assert set(first['questions']['next_action']['criteria']) == {'go', 'handoff', 'observe_again'}
    assert first['state']['page_text'] == 'Local form'
    assert first['state']['eligible_candidates'][0]['id'] == 'go'
    assert not enabled.aclose.await_count
    await tools.resources.aclose()
    assert enabled.aclose.await_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('reply,reason', [
    (answer(probability=.79), 'low_confidence'),
    (answer(confidence=.59), 'low_confidence'),
    (answer(done=.5), 'uncertain_goal'),
    (answer(choice='invented'), 'invalid_answer'),
    (answer(choice='handoff'), 'handoff'),
    (answer(choice='observe_again'), 'observe_again'),
    ({'ok': False, 'reason': 'rate_limited', 'http_status': 429, 'error': 'FAKE_SECRET'}, 'rate_limited'),
    ({'ok': False, 'reason': 'http_error', 'http_status': 429, 'error': 'FAKE_SECRET'}, 'http_error'),
    ({'ok': False, 'reason': 'timeout', 'error': 'FAKE_SECRET'}, 'timeout'),
])
async def test_uncertainty_or_api_failure_never_executes(enabled, reply, reason):
    backend = FakeBackend(); tools = session(backend)
    enabled.evaluate.return_value = reply
    result = await make_jev_browser_tools(tools)[1].ainvoke(run_args())
    assert not result['executed'] and not result['verified'] and result['handoff']
    assert result['reason'] == reason
    assert enabled.evaluate.await_count == 1 and not backend.executions
    assert backend.calls[-1]['phase'] == 'cleanup'
    assert 'FAKE_SECRET' not in json.dumps(result)
    await tools.resources.aclose()


@pytest.mark.asyncio
async def test_model_done_cannot_replace_code_verification(enabled):
    backend = FakeBackend(); tools = session(backend)
    enabled.evaluate.return_value = answer(done=.99)
    result = await make_jev_browser_tools(tools)[1].ainvoke(run_args())
    assert not result['verified'] and not backend.executions
    assert result['reason'] == 'success_unverified'
    await tools.resources.aclose()


@pytest.mark.asyncio
async def test_action_failure_is_not_success_or_replayed(enabled):
    backend = FakeBackend(); backend.fail_execute = True; tools = session(backend)
    result = await make_jev_browser_tools(tools)[1].ainvoke(run_args())
    assert not result['ok'] and not result['verified']
    assert result['attempted_ids'] == ['go'] and result['completed_ids'] == []
    assert backend.executions == ['go'] and enabled.evaluate.await_count == 1
    assert 'FAKE_SECRET' not in json.dumps(result)
    await tools.resources.aclose()


@pytest.mark.asyncio
async def test_used_candidate_cannot_be_selected_again(enabled):
    backend = FakeBackend(); tools = session(backend)
    # Keep the success condition false, then have the fake API return a stale ID.
    async def invoke(args):
        result = await FakeBackend.ainvoke(backend, args)
        backend.saved = False
        return result
    backend.ainvoke = invoke
    result = await make_jev_browser_tools(tools)[1].ainvoke(run_args())
    assert not result['verified'] and result['reason'] == 'invalid_answer'
    assert backend.executions == ['go']
    assert 'go' not in enabled.evaluate.call_args_list[1].kwargs['questions']['next_action']['criteria']
    await tools.resources.aclose()


@pytest.mark.asyncio
async def test_cancel_during_inference_cleans_pending_without_action(enabled):
    backend = FakeBackend(); tools = session(backend); entered = asyncio.Event()
    async def wait(**kwargs):
        entered.set(); await asyncio.Event().wait()
    enabled.evaluate.side_effect = wait
    task = asyncio.create_task(make_jev_browser_tools(tools)[1].ainvoke(run_args()))
    await entered.wait(); task.cancel()
    with pytest.raises(asyncio.CancelledError): await task
    assert not backend.executions and backend.calls[-1]['phase'] == 'cleanup'
    assert tools.session_gate._owner is None
    await tools.resources.aclose()


@pytest.mark.asyncio
async def test_decide_only_returns_typed_judgments_never_actions(enabled):
    backend = FakeBackend(); tools = session(backend)
    enabled.evaluate.return_value = {'ok': True, 'model': 'unit-test-fake',
        'answers': {'ready': {'type': 'noul', 'noul': .9}}, 'usage': {}}
    result = await make_jev_browser_tools(tools)[0].ainvoke({
        'questions': {'ready': {'type': 'noul', 'instructions': 'Is the form ready?'}}})
    assert result['ok'] and not result['executed'] and not result['verified']
    assert result['answers']['ready']['noul'] == .9
    assert not backend.executions
    await tools.resources.aclose()


@pytest.mark.asyncio
async def test_factory_is_idempotent_and_missing_session_fails_closed(enabled):
    backend = FakeBackend(); tools = session(backend)
    first = make_jev_browser_tools(tools)
    assert make_jev_browser_tools(tools) is first
    assert make_jev_browser_tools([backend]) == []
    await tools.resources.aclose()
    assert enabled.aclose.await_count == 1


@pytest.mark.asyncio
async def test_hard_action_budget_does_not_submit_second_candidate(enabled):
    backend = FakeBackend(); tools = session(backend)
    async def invoke(args):
        result = await FakeBackend.ainvoke(backend, args)
        backend.saved = False
        return result
    backend.ainvoke = invoke
    enabled.evaluate.side_effect = [
        answer(options=['go','second','handoff','observe_again']),
        answer(choice='second', options=['second','handoff','observe_again'])]
    result = await make_jev_browser_tools(tools)[1].ainvoke(run_args(
        candidates=[candidate(), candidate('second', '#second')], max_actions=1))
    assert result['reason'] == 'action_budget' and not result['verified']
    assert backend.executions == ['go']
    assert enabled.evaluate.await_count == 2
    await tools.resources.aclose()


@pytest.mark.asyncio
async def test_live_identity_and_freshness_with_real_mcp(monkeypatch, enabled):
    """Opt-in: real Chromium/Node/MCP, explicitly fake inference (no API)."""
    import os
    if os.getenv('DAIBOO_TEST_JEV_BROWSER_LIVE') != '1':
        pytest.skip('Set DAIBOO_TEST_JEV_BROWSER_LIVE=1 for isolated real-browser checks')
    from pathlib import Path
    import socket
    import subprocess
    import tempfile
    from playwright.async_api import async_playwright
    from test.manual.browser_runtime_smoke import fixture_server, wait_cdp
    from tools._simphtml.observer import normalize_evaluate_result
    from utils.mcp_client import create_persistent_mcp_session

    monkeypatch.setenv('DAIBOO_BROWSER_SNAPSHOT_MODE', 'none')
    monkeypatch.setenv('DAIBOO_BROWSER_ALLOW_UNSAFE_CODE', 'false')
    options = sorted(Path.home().glob('.cache/ms-playwright/chromium-*/chrome-linux64/chrome'))
    executable = os.getenv('CHROMIUM_EXECUTABLE') or (str(options[-1]) if options else None)
    assert executable, 'Install an isolated Chromium first'
    with tempfile.TemporaryDirectory(prefix='jev-test-', dir=os.getenv('TMPDIR')) as profile, fixture_server() as (base, _):
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0)); port = sock.getsockname()[1]
        process = subprocess.Popen([executable, '--headless=new', '--no-sandbox',
            '--remote-debugging-address=127.0.0.1', f'--remote-debugging-port={port}',
            f'--user-data-dir={profile}', '--no-proxy-server', '--disable-dev-shm-usage', 'about:blank'],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            await wait_cdp(port, process)
            endpoint = f'http://127.0.0.1:{port}'
            async with create_persistent_mcp_session(endpoint) as mcp_tools, async_playwright() as pw:
                if not hasattr(mcp_tools, 'resources'): mcp_tools.resources = AsyncExitStack()
                tools = {t.name: t for t in mcp_tools}
                helpers = {t.name: t for t in make_jev_browser_tools(mcp_tools)}
                external = await pw.chromium.connect_over_cdp(endpoint)
                page = external.contexts[0].pages[0]

                async def reset():
                    enabled.evaluate.reset_mock(side_effect=True)
                    enabled.evaluate.return_value = answer()
                    await tools['browser_navigate'].ainvoke({'url': base + '/review'})
                    await page.locator('#status').wait_for()

                async def assert_clean():
                    code = "async (page) => ({sizes: Object.getOwnPropertySymbols(page.context()).filter(s=>String(s).includes('daiboo.jev.')).map(s=>page.context()[s].size)})"
                    raw = await mcp_tools.all_tools['browser_run_code_unsafe'].ainvoke({'code': code})
                    sizes = json.loads(normalize_evaluate_result(raw))['sizes']
                    assert sizes and all(n == 0 for n in sizes), sizes

                await reset()
                enabled.evaluate.side_effect = [answer(), answer(choice='handoff', done=.99, options=['handoff','observe_again'])]
                result = await helpers['browser_jev_run'].ainvoke(run_args(
                    candidates=[candidate(target='#danger')], success_checks=[{'target':'#status','text':'CLICKED','match':'exact'}]))
                assert result['ok'] and result['verified'] and result['completed_ids'] == ['go'], result
                assert await page.locator('#status').inner_text() == 'CLICKED'
                await assert_clean()

                changes = {
                    'navigation': lambda: page.goto(base + '/review/destination'),
                    'same_url_reload': lambda: page.reload(),
                    'document_open_write': lambda: page.evaluate('() => { document.open(); document.write("<html><body><h1 id=status>Replacement</h1><button id=danger>Target</button></body></html>");document.close(); }'),
                    'root_replacement': lambda: page.evaluate('() => document.documentElement.replaceWith(document.documentElement.cloneNode(true))'),
                    'element_replacement': lambda: page.evaluate('() => { const el=document.querySelector("#danger");el.replaceWith(el.cloneNode(true)); }'),
                    'attribute_mutation': lambda: page.evaluate('() => document.querySelector("#danger").setAttribute("data-version", "changed")'),
                    'attribute_revert': lambda: page.evaluate('() => { const e=document.querySelector("#danger");e.setAttribute("title","changed");e.removeAttribute("title"); }'),
                    'spa_text_mutation': lambda: page.evaluate('() => document.querySelector("#status").textContent="External update"'),
                    'property_value_mutation': lambda: page.evaluate('() => document.querySelector("#name").value="external"'),
                    'popup': lambda: page.evaluate('() => window.open("/review/destination", "_blank")'),
                }
                for label, change in changes.items():
                    await reset()
                    async def inference(*, state, questions, change=change):
                        assert 'AuditFakeSecret12345' not in json.dumps(state)
                        await change(); return answer()
                    enabled.evaluate.side_effect = inference
                    result = await helpers['browser_jev_run'].ainvoke(run_args(candidates=[candidate(target='#danger')]))
                    assert not result['verified'] and result['completed_ids'] == [], (label, result)
                    assert await page.locator('#status').inner_text() != 'CLICKED', (label, result)
                    assert enabled.evaluate.await_count == 1, (label, result)
                    assert 'AuditFakeSecret12345' not in json.dumps(result), (label, result)
                    for popup in list(external.contexts[0].pages):
                        if popup != page: await popup.close()
                    await assert_clean()

                # Hidden/CSS-only success text must not verify business success.
                for hidden in ('display:none', 'visibility:hidden'):
                    await reset()
                    await page.evaluate('(hidden) => { const s=document.createElement("span");s.style.cssText=hidden;s.textContent="Saved";document.querySelector("#status").replaceChildren(s); }', hidden)
                    enabled.evaluate.return_value = answer(done=.99)
                    result = await helpers['browser_jev_run'].ainvoke(run_args(candidates=[candidate(target='#danger')]))
                    assert not result['verified'] and not result['attempted_ids'], (hidden, result)
                    await assert_clean()

                # Same element .value property changes bypass MutationObserver.
                await reset()
                async def change_value(**kwargs):
                    await page.evaluate('() => document.querySelector("#name").value="changed"')
                    return answer()
                enabled.evaluate.side_effect = change_value
                result = await helpers['browser_jev_run'].ainvoke(run_args(
                    candidates=[candidate(target='#name', op='fill', value='Should not write')]))
                assert result['reason'] in {'element_changed', 'page_changed'} and result['completed_ids'] == [], result
                assert await page.locator('#name').input_value() == 'changed'
                await assert_clean()

                # Sensitive .value getters are not invoked by observation.
                await reset()
                await page.evaluate('() => { window.passwordReads=0;Object.defineProperty(document.querySelector("#pw"),"value",{get(){window.passwordReads++;return "UnexpectedPasswordGetter";}}); }')
                enabled.evaluate.return_value = {'ok': True, 'model': 'unit-test-fake', 'usage': {},
                    'answers': {'ready': {'type': 'noul', 'noul': .99}}}
                observed = await helpers['browser_jev_decide'].ainvoke({'questions': {'ready': {'type':'noul','instructions':'Is a form present?'}}})
                assert observed['ok'], observed
                state = enabled.evaluate.call_args.kwargs['state']
                assert 'AuditFakeSecret12345' not in json.dumps(state) and 'UnexpectedPasswordGetter' not in json.dumps(state)
                assert await page.evaluate('() => window.passwordReads') == 0
                await assert_clean()

                await reset(); entered = asyncio.Event()
                async def blocked(**kwargs):
                    entered.set(); await asyncio.Event().wait()
                enabled.evaluate.side_effect = blocked
                task = asyncio.create_task(helpers['browser_jev_run'].ainvoke(run_args(candidates=[candidate(target='#danger')])))
                await asyncio.wait_for(entered.wait(), 10); task.cancel()
                with pytest.raises(asyncio.CancelledError): await task
                assert await page.locator('#status').inner_text() != 'CLICKED'
                await assert_clean()
                await mcp_tools.resources.aclose()
        finally:
            process.terminate()
            try: process.wait(timeout=15)
            except subprocess.TimeoutExpired: process.kill(); process.wait(timeout=5)
