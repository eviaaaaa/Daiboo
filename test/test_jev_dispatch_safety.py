"""Fixed Jev JS regressions: real owned Chromium/MCP, never model inference.

Opt in with DAIBOO_TEST_JEV_BROWSER_LIVE=1. All CDP/profile/process resources
belong to this module; no user browser, provider credentials or external API.
"""
from contextlib import AsyncExitStack
import asyncio
import json
import os
from pathlib import Path
import socket
import subprocess
import tempfile
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio

from test.test_jev_browser import answer, candidate, run_args
from tools.jev_browser import make_jev_browser_tools
from tools._simphtml.observer import normalize_evaluate_result

pytestmark = pytest.mark.asyncio(loop_scope='module')


@pytest_asyncio.fixture(scope='module', loop_scope='module')
async def browser():
    if os.getenv('DAIBOO_TEST_JEV_BROWSER_LIVE') != '1':
        pytest.skip('Set DAIBOO_TEST_JEV_BROWSER_LIVE=1 for owned Chromium/MCP')
    from playwright.async_api import async_playwright
    from test.manual.browser_runtime_smoke import fixture_server, wait_cdp
    from utils.mcp_client import create_persistent_mcp_session

    options = sorted(Path.home().glob('.cache/ms-playwright/chromium-*/chrome-linux64/chrome'))
    executable = os.getenv('CHROMIUM_EXECUTABLE') or (str(options[-1]) if options else None)
    assert executable, 'Install isolated Chromium before enabling live tests'
    ready = asyncio.get_running_loop().create_future()
    stop = asyncio.Event()

    async def own_session():
        try:
            await serve_session()
        except BaseException as error:
            if not ready.done():
                ready.set_exception(error)
            raise

    async def serve_session():
        with tempfile.TemporaryDirectory(prefix='jev-dispatch-', dir=os.getenv('TMPDIR')) as profile, fixture_server() as (base, _):
            with socket.socket() as sock:
                sock.bind(('127.0.0.1', 0))
                port = sock.getsockname()[1]
            process = subprocess.Popen([executable, '--headless=new', '--no-sandbox',
                '--remote-debugging-address=127.0.0.1', f'--remote-debugging-port={port}',
                f'--user-data-dir={profile}', '--no-proxy-server', '--disable-dev-shm-usage', 'about:blank'],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            try:
                await wait_cdp(port, process)
                endpoint = f'http://127.0.0.1:{port}'
                async with create_persistent_mcp_session(endpoint) as tools, async_playwright() as pw:
                    if not hasattr(tools, 'resources'):
                        tools.resources = AsyncExitStack()
                    external = await pw.chromium.connect_over_cdp(endpoint)
                    page = external.contexts[0].pages[0]
                    await next(t for t in tools if t.name == 'browser_navigate').ainvoke({'url': base + '/review'})
                    backend = tools.all_tools['browser_run_code_unsafe']

                    async def invoke(code):
                        raw = await backend.ainvoke({'code': code})
                        return raw if isinstance(raw, dict) and 'ok' in raw else json.loads(normalize_evaluate_result(raw))

                    ready.set_result(SimpleNamespace(page=page, tools=tools, backend=backend, invoke=invoke))
                    await stop.wait()
                    await tools.resources.aclose()
            finally:
                process.terminate()
                try:
                    process.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)

    owner = asyncio.create_task(own_session())
    try:
        yield await ready
    finally:
        stop.set()
        await owner


def helpers(browser, monkeypatch, reply=None):
    import utils.typesafe_client as client_module
    fake = SimpleNamespace(model='dispatch-fixture-no-inference',
                           evaluate=AsyncMock(return_value=reply or answer()), aclose=AsyncMock())
    monkeypatch.setattr(client_module, 'jev_enabled', lambda: True)
    monkeypatch.setattr(client_module.JevClient, 'from_env', lambda: fake)
    # A fresh helper cache for each case, on the same owned MCP session.
    if hasattr(browser.tools, '_jev_browser_tools'):
        del browser.tools._jev_browser_tools
    return {t.name: t for t in make_jev_browser_tools(browser.tools)}, fake


async def assert_clean(browser):
    result = await browser.invoke("""async page => ({ok: true,
        sizes: Object.getOwnPropertySymbols(page.context()).filter(s => String(s).includes('daiboo.jev.')).map(s => page.context()[s].size)})""")
    assert result['sizes'] and all(size == 0 for size in result['sizes']), result
    # A stale handler must not poison subsequent actions on the same page.
    await browser.page.set_content('<button id="after" onclick="window.afterClicks++">After</button><script>window.afterClicks=0</script>')
    clicked = await browser.invoke("async page => { await page.locator('#after').click({timeout:500}); return {ok:true}; }")
    assert clicked['ok'] and await browser.page.evaluate('() => window.afterClicks') == 1


async def test_locator_handler_can_block_native_retry_until_timeout(browser):
    """Public API feasibility: hold, do NOT throw or race the native action."""
    await browser.page.set_content('<button id="go" onclick="window.clicks++">Go</button><div style="position:fixed;inset:0;z-index:10">Overlay</div><script>window.clicks=0</script>')
    result = await browser.invoke("""async page => {
        const body = page.locator('body');
        let calls=0, release;
        const blocked = new Promise(resolve => { release=resolve; });
        await page.addLocatorHandler(body, async () => { if (++calls >= 2) await blocked; }, {noWaitAfter:true});
        let timedOut=false;
        try { await page.locator('#go').click({timeout:350}); }
        catch (e) { timedOut=e.name === 'TimeoutError'; }
        finally { release(); await page.removeLocatorHandler(body); }
        await page.evaluate(() => document.querySelector('div').remove());
        await page.waitForTimeout(100);
        return {ok:true, calls, timedOut, clicks:await page.evaluate(() => window.clicks)};
    }""")
    assert result['calls'] >= 2 and result['timedOut'] and result['clicks'] == 0, result


async def test_covered_unchanged_target_hands_off_instead_of_autowait(browser, monkeypatch):
    await browser.page.set_content('''<button id="go" onclick="window.clicks++">Save draft</button>
        <div id="status">Unsaved</div><div id="overlay" style="position:fixed;inset:0;z-index:10">Loading</div>
        <script>window.clicks=0</script>''')
    tools, fake = helpers(browser, monkeypatch)
    result = await tools['browser_jev_run'].ainvoke(run_args(max_actions=1))
    assert result['reason'] == 'not_actionable' and result['completed_ids'] == [], result
    assert fake.evaluate.await_count == 1
    await browser.page.evaluate('() => document.querySelector("#overlay").remove()')
    await asyncio.sleep(.3)
    assert await browser.page.evaluate('() => window.clicks') == 0
    await assert_clean(browser)


@pytest.mark.parametrize('delay_ms', [180, 300, 550])
async def test_autowait_changed_button_is_never_clicked(browser, monkeypatch, delay_ms):
    page = browser.page
    await page.set_content('''<button id="go" onclick="window.saved++">Save draft</button>
        <div id="status">Unsaved</div>
        <div id="overlay" style="position:fixed;inset:0;background:white;z-index:1000">Loading</div>
        <script>window.saved=0;window.deleted=0;</script>''')
    native_backend = browser.backend
    class ScheduleChange:
        async def ainvoke(self, args):
            cfg = json.loads(json.loads(args['code'].split('JSON.parse(', 1)[1].split(');', 1)[0]))
            if cfg['phase'] == 'execute':
                await page.evaluate('''delay => setTimeout(() => {
                    const button=document.querySelector('#go');
                    button.textContent='Delete record';
                    button.onclick=() => { window.deleted++; document.querySelector('#status').textContent='DELETED'; };
                    document.querySelector('#overlay').remove();
                }, delay)''', delay_ms)
            return await native_backend.ainvoke(args)
    monkeypatch.setitem(browser.tools.all_tools, 'browser_run_code_unsafe', ScheduleChange())
    tools, fake = helpers(browser, monkeypatch)
    fake.evaluate.side_effect = [answer(), answer(choice='handoff', done=.99, options=['handoff', 'observe_again'])]
    result = await tools['browser_jev_run'].ainvoke(run_args(max_actions=1))
    # Wait beyond native action timeout and overlay removal to detect late clicks.
    await asyncio.sleep(1.1)
    state = await page.evaluate('() => ({saved,deleted,text:document.querySelector("#go").textContent})')
    assert state == {'saved': 0, 'deleted': 0, 'text': 'Delete record'}, (result, state)
    assert not result['verified'] and result['completed_ids'] == [], result
    assert result['reason'] in {'page_changed', 'element_changed', 'not_actionable'}, result
    assert fake.evaluate.await_count == 1
    await assert_clean(browser)


@pytest.mark.parametrize('ancestor', [
    'style="opacity:0"', 'aria-hidden="true"', 'hidden', 'style="display:none"',
    'style="visibility:hidden"', 'style="content-visibility:hidden"',
])
async def test_hidden_ancestor_text_cannot_verify_success(browser, monkeypatch, ancestor):
    await browser.page.set_content(f'<button id="go">Save</button><section {ancestor}><div><span id="status">Saved</span></div></section>')
    tools, fake = helpers(browser, monkeypatch, answer(choice='handoff', done=.99))
    result = await tools['browser_jev_run'].ainvoke(run_args())
    assert not result['verified'] and not result['attempted_ids'], (ancestor, result)
    assert result['reason'] == 'handoff', result
    assert fake.evaluate.call_args.kwargs['state']['observed_check_matches'] == [False]
    await assert_clean(browser)


async def test_visible_success_text_still_verifies(browser, monkeypatch):
    await browser.page.set_content('<button id="go">Save</button><section><div><span id="status">Saved</span></div></section>')
    tools, _ = helpers(browser, monkeypatch, answer(done=.99))
    result = await tools['browser_jev_run'].ainvoke(run_args())
    assert result['verified'] and not result['attempted_ids'], result
    await assert_clean(browser)


@pytest.mark.parametrize('op,target,value,html', [
    ('click', '#go', None, '<button id="go" onclick="window.changes++">Save</button>'),
    ('fill', '#go', 'Edited', '<input id="go" oninput="window.changes++">'),
    ('select', '#go', 'b', '<select id="go" onchange="window.changes++"><option value="a">A</option><option value="b">B</option></select>'),
    ('check', '#go', None, '<input id="go" type="checkbox" onchange="window.changes++">'),
])
async def test_fresh_native_actions_still_work(browser, monkeypatch, op, target, value, html):
    await browser.page.set_content(html + '<div id="status">Unsaved</div><script>window.changes=0</script>')
    tools, fake = helpers(browser, monkeypatch)
    fake.evaluate.side_effect = [answer(), answer(choice='handoff', options=['handoff', 'observe_again'])]
    extra = {} if value is None else {'value': value}
    result = await tools['browser_jev_run'].ainvoke(run_args(candidates=[candidate(op=op, target=target, **extra)], max_actions=1))
    assert result['completed_ids'] == ['go'], result
    assert await browser.page.evaluate('() => window.changes') >= 1
    await assert_clean(browser)
