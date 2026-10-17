"""Isolated Chromium/CDP + real persistent Playwright MCP regression smoke.

Run from repository root: uv run --python 3.11 python test/manual/browser_runtime_smoke.py
No model, credentials or user browser are used. HTTP/CDP bind loopback with random
ports; a temporary profile and owned Chromium process are always cleaned up.
JSON metrics compare tool response characters/calls, NOT LLM tokens or latency.
"""
from __future__ import annotations

import asyncio
from contextlib import contextmanager
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from langchain_core.messages import ToolMessage
from playwright.async_api import async_playwright
from tools.browser_runtime import make_browser_runtime_tools
from tools.web_observe_tool import WebObserveTool
from tools._simphtml import find_evaluate_tool, observe_simplified
from tools._simphtml.observer import normalize_evaluate_result
from utils.mcp_client import create_persistent_mcp_session


FIXTURE = r'''<!doctype html><html><head><title>Daiboo isolated SPA</title></head>
<body><header><h1>Runtime smoke</h1></header><main id="main"><form id="profile">
<label>Name <input id="name" name="display-name"></label>
<label>Plan <select id="plan"><option value="free">Free</option><option value="pro">Pro</option></select></label>
<button id="save" type="button">Save locally</button></form>
<p id="status" role="status">Unsaved</p><div id="toast"></div>
<label>Secret placeholder <input id="password" type="password" value="test-sensitive-placeholder"></label>
<div id="long">LONG_TEXT</div><iframe src="/frame" title="Same-origin frame"></iframe>
<div id="shadow"></div><section id="catalog"><h2>Catalog</h2>CATALOG</section></main>
<script>
let state = {name:'', count:0};
nameField = document.getElementById('name');
nameField.addEventListener('input', e => {state.name=e.target.value; nameField.value=state.name});
document.querySelector('#save').onclick = async () => {
  const payload={name:state.name,plan:document.querySelector('#plan').value};
  await fetch('/save',{method:'POST',body:JSON.stringify(payload)});
  state.count++; history.pushState({},'', '#saved');
  document.querySelector('#status').textContent=`Saved ${state.name} ${payload.plan} ${state.count}`;
  document.querySelector('#toast').textContent='Saved successfully in isolated local fixture';
  setTimeout(()=>document.querySelector('#toast').textContent='',1200);
};
document.querySelector('#shadow').attachShadow({mode:'open'}).innerHTML='<button>Shadow action</button>';
</script></body></html>'''.replace('LONG_TEXT', 'x' * 9000).replace('CATALOG', ''.join(
    f'<article><h3>Item {i}</h3><p>Details for catalog record {i}</p><button>Choose item {i}</button></article>' for i in range(120)))


REVIEW_FIXTURE = r'''<!doctype html><html><body>
<h1 id="status">Original document</h1><input id="name">
<input id="pw" type="password" value="AuditFakeSecret12345">
<input id="hidden" type="password" value="AuditFakeSecret12345" hidden>
<button id="go" onclick="location.href='/review/destination'">Navigate</button>
<button id="reload" onclick="location.reload()">Reload</button>
<button id="popup" onclick="window.open('/review/destination','_blank')">Popup</button>
<button id="replace">Replace document</button>
<button id="later" onclick="setTimeout(()=>location.href='/review/destination',150)">Later navigation</button>
<button id="duplicate" onclick="document.querySelector('#name').insertAdjacentHTML('afterend','<input class=unique type=password value=AuditFakeSecret12345>')">Duplicate</button>
<button id="danger" onclick="document.querySelector('#status').textContent='CLICKED'">Harmless marker</button>
<script>
document.querySelector('#name').className='unique';
document.querySelector('#replace').onclick=()=>{
 document.open(); document.write('<!doctype html><html><body><h1 id="status">Replaced document</h1><button id="danger" onclick="document.querySelector(\'#status\').textContent=\'CLICKED\'">Marker</button></body></html>'); document.close();
};
if(location.pathname.endsWith('/destination')) {
 document.querySelector('#status').textContent='Destination document';
 document.body.insertAdjacentHTML('beforeend','<div id="gate">Ready</div>');
}
</script></body></html>'''


@contextmanager
def fixture_server():
    saved = []
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format, *args): pass
        def do_GET(self):
            body = (REVIEW_FIXTURE if self.path.startswith('/review') else
                    '<!doctype html><html><body><button>Frame action</button></body></html>' if self.path.startswith('/frame') else FIXTURE)
            self.send_response(200); self.send_header('Content-Type', 'text/html; charset=utf-8'); self.end_headers(); self.wfile.write(body.encode())
        def do_POST(self):
            payload=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            saved.append(payload)
            self.send_response(200); self.end_headers(); self.wfile.write(b'ok')
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    try: yield f'http://127.0.0.1:{server.server_port}', saved
    finally: server.shutdown(); server.server_close(); thread.join(timeout=3)


async def wait_cdp(port, process):
    for _ in range(100):
        if process.poll() is not None: raise RuntimeError('Isolated Chromium exited before CDP readiness')
        try:
            _, writer = await asyncio.open_connection('127.0.0.1', port)
            writer.close(); await writer.wait_closed(); return
        except OSError: await asyncio.sleep(.1)
    raise RuntimeError('Isolated CDP readiness timeout')


def chars(value): return len(json.dumps(value, ensure_ascii=False, default=str))


async def exercise(endpoint, base, saved):
    metrics = {}
    # Native full snapshots are the baseline; none is the configured fast path.
    for mode in ('full', 'none'):
        os.environ['DAIBOO_BROWSER_SNAPSHOT_MODE'] = mode
        async with create_persistent_mcp_session(endpoint) as mcp_tools:
            tools = {t.name:t for t in mcp_tools}
            helpers = {t.name:t for t in make_browser_runtime_tools(mcp_tools)}
            info = await helpers['browser_runtime_info'].ainvoke({})
            assert info['batch_available'] is True, info
            assert info['interactive_snapshot'] is False, info
            assert 'target' in info['snapshot_options'] and 'depth' in info['snapshot_options'], info
            assert 'browser_run_code_unsafe' not in tools
            await tools['browser_navigate'].ainvoke({'url':base})
            full_snapshot = await tools['browser_snapshot'].ainvoke({})
            local_snapshot = await tools['browser_snapshot'].ainvoke({'target':'#profile','depth':2})
            assert 'Name' in str(local_snapshot) and 'Catalog' not in str(local_snapshot)
            assert chars(local_snapshot) < chars(full_snapshot)
            responses=[]
            start=time.perf_counter()
            for name, args in [
                ('browser_type', {'target':'#name','text':'Native Alice'}),
                ('browser_select_option', {'target':'#plan','values':['pro']}),
                ('browser_click', {'target':'#save'}),
                ('browser_evaluate', {'function':'() => document.querySelector("#status").textContent'}),
            ]:
                responses.append(await tools[name].ainvoke(args))
            assert 'Saved Native Alice pro' in normalize_evaluate_result(responses[-1]), responses[-1]
            assert saved[-1] == {'name':'Native Alice','plan':'pro'}, saved
            metrics[mode] = {'native_calls':len(responses),'native_response_chars':sum(map(chars,responses)),
                'seconds':round(time.perf_counter()-start,3), 'full_snapshot_chars':chars(full_snapshot),'local_snapshot_chars':chars(local_snapshot)}
            if mode == 'full': continue
            await tools['browser_navigate'].ainvoke({'url':base})
            batch=helpers['browser_batch']
            start=time.perf_counter()
            result=await batch.ainvoke({'steps':[
                {'op':'fill','target':'#name','value':'Batch Alice'},
                {'op':'select','target':'#plan','value':'pro'},
                {'op':'click','target':'#save'},
                {'op':'assert_text','target':'#status','value':'Saved Batch Alice pro'},
                {'op':'read_text','target':'#status'},
            ],'max_chars':200})
            assert result['ok'] is True and result['verified'] is True, result
            assert result['completed'] == 5 and 'Saved Batch Alice pro' in result['reads'][0]['value'], result
            assert saved[-1] == {'name':'Batch Alice','plan':'pro'}
            metrics['batch']={'backend_calls':1,'response_chars':chars(result),'seconds':round(time.perf_counter()-start,3)}
            read=await batch.ainvoke({'steps':[{'op':'read_text','target':'#long'}],'max_chars':200})
            assert read['ok'] and read['truncated'] and len(read['reads'][0]['value']) <= 200, read
            fail=await batch.ainvoke({'steps':[
                {'op':'fill','target':'#name','value':'Do not replay'},
                {'op':'click','target':'#absent'},
                {'op':'click','target':'#save'},
            ],'timeout_ms':200})
            assert not fail['ok'] and fail['completed'] == 1 and fail['failed_step'] == 1, fail
            verified_before_write = await batch.ainvoke({'steps':[
                {'op':'assert_text','target':'#status','value':'Saved Batch Alice pro'},
                {'op':'fill','target':'#name','value':'Unverified change'},
            ]})
            assert verified_before_write['ok'] and not verified_before_write['verified'], verified_before_write
            protected=await batch.ainvoke({'steps':[{'op':'read_value','target':'#password'}]})
            assert not protected['ok'] and 'Sensitive field blocked' in protected['error'], protected
            # Malicious caller strings remain inert data, not server-side JS.
            attack='\"); throw new Error("injected"); // 😀'
            injection=await batch.ainvoke({'steps':[
                {'op':'fill','target':'#name','value':attack},
                {'op':'read_value','target':'#name'},
            ]})
            assert injection['ok'] and injection['reads'][0]['value'] == attack, injection
            # Native tabs retain exact current-page selection; no fuzzy matching.
            await tools['browser_tabs'].ainvoke({'action':'new','url':base+'/second'})
            tabs=await tools['browser_tabs'].ainvoke({'action':'list'})
            assert '/second' in str(tabs), tabs
            await tools['browser_tabs'].ainvoke({'action':'select','index':0})
            verify_tab=await tools['browser_evaluate'].ainvoke({'function':'() => location.pathname'})
            assert normalize_evaluate_result(verify_tab) == '/', verify_tab
            await tools['browser_tabs'].ainvoke({'action':'close','index':1})
            # Exercise the actual diff middleware around a live browser write.
            from loggers.diff_middleware import make_diff_middleware
            middleware=make_diff_middleware(mcp_tools)
            request=SimpleNamespace(tool=tools['browser_type'])
            async def handler(_):
                raw=await tools['browser_type'].ainvoke({'target':'#name','text':'Diff Alice'})
                return ToolMessage(content=json.dumps(raw), name='browser_type',tool_call_id='smoke-diff')
            diff=await middleware.awrap_tool_call(request,handler)
            assert '[diff]' in str(diff.content) and 'Diff Alice' in str(diff.content), diff
            # Enforce hard budgets for both text and HTML; include same-origin
            # frame/Shadow DOM and secret-redaction checks against real DOM.
            observer=WebObserveTool(mcp_tools=mcp_tools)
            for text_only in (True, False):
                observation=await observer.ainvoke({'text_only':text_only,'max_chars':2000})
                assert observation['ok'] and observation['truncated'], observation
                assert observation['char_count'] == len(observation['content']) <= 2000
            body=await observe_simplified(find_evaluate_tool(mcp_tools), text_only=False)
            assert body and 'Frame action' in body and 'Shadow action' in body
            assert 'test-sensitive-placeholder' not in body, 'web_observe leaked a password value'
            metrics['checks']=['form','SPA input events','local save read-back','partial/depth snapshot',
                'batch budget','partial failure','sensitive field blocked','inert code injection',
                'tabs exact selection','live diff middleware','HTML/text budget','same-origin iframe','open Shadow DOM','secret redaction']
    return metrics


async def exercise_review(endpoint, base):
    """Independent-review regressions: real DOM/navigation and shared MCP gate."""
    from loggers.diff_middleware import make_diff_middleware
    checks = {}
    async with create_persistent_mcp_session(endpoint) as mcp_tools:
        tools = {t.name: t for t in mcp_tools}
        helpers = {t.name: t for t in make_browser_runtime_tools(mcp_tools)}
        batch = helpers['browser_batch']

        async def reset():
            await tools['browser_navigate'].ainvoke({'url': base + '/review'})

        async def evaluate(function):
            return normalize_evaluate_result(await tools['browser_evaluate'].ainvoke({'function': function}))

        async def concurrent_with_batch(steps, tool, args):
            first = asyncio.create_task(batch.ainvoke({'steps': steps, 'timeout_ms': 300}))
            # Start the competing real tool only once the real batch owns the
            # gate (without substituting any action/backend/navigation).
            async def owned():
                while mcp_tools.session_gate._owner is None:
                    await asyncio.sleep(.001)
            await asyncio.wait_for(owned(), 2)
            second = asyncio.create_task(tool.ainvoke(args))
            return await asyncio.wait_for(asyncio.gather(first, second), 10)

        await reset()
        details = await helpers['browser_runtime_info'].ainvoke({'tool_names': ['browser_evaluate', 'browser_run_code_unsafe']})
        assert details['schemas']['browser_evaluate'] == tools['browser_evaluate'].args_schema
        assert details['schemas']['browser_evaluate']['required'] == ['function']
        assert details['schemas']['browser_evaluate']['additionalProperties'] is False
        assert details['unknown_tools'] == ['browser_run_code_unsafe']
        checks['complete_public_schema'] = True

        for label, steps in [
            ('ambiguous_password_selector', [{'op': 'read_value', 'target': 'input'}]),
            ('unique_becomes_ambiguous', [{'op': 'click', 'target': '#duplicate'}, {'op': 'read_value', 'target': '.unique'}]),
            ('hidden_sensitive_timeout', [{'op': 'click', 'target': '#hidden'}]),
        ]:
            await reset()
            result = await batch.ainvoke({'steps': steps, 'timeout_ms': 150})
            assert not result['ok'], (label, result)
            assert 'AuditFakeSecret12345' not in json.dumps(result), label
            assert 'Call log' not in json.dumps(result) and 'strict mode' not in json.dumps(result), label
            checks[label] = result

        for label, trigger in [('cross_navigation', '#go'), ('same_url_reload', '#reload'),
                               ('document_open_write', '#replace'), ('popup', '#popup')]:
            await reset()
            result = await batch.ainvoke({'steps': [
                {'op': 'click', 'target': trigger},
                {'op': 'click', 'target': '#danger'},
                {'op': 'read_text', 'target': '#status'},
            ]})
            assert not result['ok'] and result['reason'] == 'page_changed', (label, result)
            assert result['completed'] == 1 and result['failed_step'] == 1 and not result['verified'], (label, result)
            readback = await evaluate('() => document.querySelector("#status").textContent')
            assert 'CLICKED' not in readback, (label, readback)
            if label == 'popup':
                await tools['browser_tabs'].ainvoke({'action': 'select', 'index': 1})
                assert 'CLICKED' not in await evaluate('() => document.querySelector("#status").textContent')
                await tools['browser_tabs'].ainvoke({'action': 'close', 'index': 1})
            checks[label] = {'result': result, 'readback': readback}

        # Direct CDP setup avoids the native MCP evaluate tool's post-action
        # settle delay consuming the 150ms BEFORE the batch has even started.
        # This is a second client to our OWN temporary Chromium, not a mock.
        for label, prepare in [
            ('write_target_missing_during_navigation', '() => { document.querySelector("#danger").remove(); setTimeout(() => location.href="/review/destination", 150); }'),
            ('write_target_hidden_during_navigation', '() => { document.querySelector("#danger").hidden=true; setTimeout(() => location.href="/review/destination", 150); }'),
            ('write_target_replaced_in_same_document', '() => { const old=document.querySelector("#danger"); old.hidden=true; setTimeout(() => { const next=old.cloneNode(true); next.hidden=false; old.replaceWith(next); }, 150); }'),
        ]:
            await reset()
            async with async_playwright() as external_pw:
                external_browser = await external_pw.chromium.connect_over_cdp(endpoint)
                external_page = next(p for p in external_browser.contexts[0].pages if p.url == base + '/review')
                await external_page.evaluate(prepare)
                stale_write = await batch.ainvoke({'steps': [{'op': 'click', 'target': '#danger'}], 'timeout_ms': 2000})
                stale_readback = await external_page.locator('#status').inner_text()
            assert 'CLICKED' not in stale_readback, (label, stale_write, stale_readback)
            assert not stale_write['ok'] and stale_write['completed'] == 0, (label, stale_write)
            checks[label] = {'result': stale_write, 'readback': stale_readback}

        await reset()
        asynchronous = await batch.ainvoke({'steps': [
            {'op': 'click', 'target': '#later'}, {'op': 'wait_for', 'target': '#gate'},
            {'op': 'click', 'target': '#danger'},
        ], 'timeout_ms': 2000})
        assert not asynchronous['ok'] and asynchronous['reason'] == 'page_changed', asynchronous
        assert asynchronous['completed'] == 1, asynchronous
        assert 'CLICKED' not in await evaluate('() => document.querySelector("#status").textContent')
        checks['navigation_during_wait'] = asynchronous

        # Different roots: a navigate must not rescue the batch's missing gate
        # by moving its remaining locator actions into the destination document.
        await reset()
        result, _ = await concurrent_with_batch([
            {'op': 'wait_for', 'target': '#gate'}, {'op': 'click', 'target': '#danger'},
        ], tools['browser_navigate'], {'url': base + '/review/destination'})
        assert not result['ok'] and result['completed'] == 0, result
        assert await evaluate('() => document.querySelector("#status").textContent') == 'Destination document'
        checks['batch_plus_navigate'] = result

        await tools['browser_tabs'].ainvoke({'action': 'new', 'url': base + '/review/destination'})
        await tools['browser_tabs'].ainvoke({'action': 'select', 'index': 0})
        await reset()
        result, _ = await concurrent_with_batch([
            {'op': 'wait_for', 'target': '#gate'}, {'op': 'click', 'target': '#danger'},
        ], tools['browser_tabs'], {'action': 'select', 'index': 1})
        assert not result['ok'] and result['completed'] == 0, result
        assert await evaluate('() => document.querySelector("#status").textContent') == 'Destination document'
        await tools['browser_tabs'].ainvoke({'action': 'close', 'index': 1})
        checks['batch_plus_tab_select'] = result

        await reset()
        result, _ = await concurrent_with_batch([
            {'op': 'fill', 'target': '#name', 'value': 'Batch owner'},
            {'op': 'wait_for', 'target': '#absent'},
        ], tools['browser_type'], {'target': '#name', 'text': 'Atomic after batch'})
        assert not result['ok'] and result['completed'] == 1, result
        assert await evaluate('() => document.querySelector("#name").value') == 'Atomic after batch'
        checks['batch_plus_atomic_write'] = result

        await reset()
        first = asyncio.create_task(tools['browser_evaluate'].ainvoke({'function': 'async () => { window.order=["first-start"]; await new Promise(r=>setTimeout(r,150)); window.order.push("first-end"); }'}))
        await asyncio.sleep(.03)
        second = asyncio.create_task(tools['browser_evaluate'].ainvoke({'function': '() => window.order.push("second")'}))
        await asyncio.wait_for(asyncio.gather(first, second), 5)
        order = (await evaluate('() => window.order.join("|")')).split('|')
        assert order == ['first-start', 'first-end', 'second'], order
        checks['atomic_plus_atomic'] = order

        # The actual observer, transient monitors and actual write all execute
        # nested StructuredTools under the middleware's one operation nonce.
        await reset()
        middleware = make_diff_middleware(mcp_tools)
        action_done = asyncio.Event()
        async def handler(_):
            raw = await tools['browser_type'].ainvoke({'target': '#name', 'text': 'Diff owner'})
            action_done.set()
            await asyncio.sleep(.15)
            return ToolMessage(content=json.dumps(raw), name='browser_type', tool_call_id='review-diff')
        first = asyncio.create_task(middleware.awrap_tool_call(SimpleNamespace(tool=tools['browser_type']), handler))
        await asyncio.wait_for(action_done.wait(), 10)
        second = asyncio.create_task(tools['browser_type'].ainvoke({'target': '#name', 'text': 'Diff outsider'}))
        diff, _ = await asyncio.wait_for(asyncio.gather(first, second), 15)
        assert '[diff]' in diff.content and 'Diff owner' in diff.content and 'Diff outsider' not in diff.content, diff.content
        assert await evaluate('() => document.querySelector("#name").value') == 'Diff outsider'
        checks['diff_critical_region'] = True
    return checks


async def main():
    os.environ['DAIBOO_BROWSER_ALLOW_UNSAFE_CODE']='false'
    async with async_playwright() as pw:
        executable=os.getenv('CHROMIUM_EXECUTABLE') or pw.chromium.executable_path
        if not Path(executable).is_file():
            candidates=sorted(Path.home().glob('.cache/ms-playwright/chromium-*/chrome-linux64/chrome'))
            executable=str(candidates[-1]) if candidates else shutil.which('chromium')
        if not executable: raise RuntimeError('Install Chromium or set CHROMIUM_EXECUTABLE')
    with tempfile.TemporaryDirectory(prefix='daiboo-runtime-smoke-') as profile, fixture_server() as (base,saved):
        with socket.socket() as s: s.bind(('127.0.0.1',0)); port=s.getsockname()[1]
        process=subprocess.Popen([executable,'--headless=new','--no-sandbox',
            '--remote-debugging-address=127.0.0.1',f'--remote-debugging-port={port}',
            f'--user-data-dir={profile}','--no-proxy-server','--disable-dev-shm-usage','about:blank'],
            stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        try:
            await wait_cdp(port,process)
            metrics=await exercise(f'http://127.0.0.1:{port}',base,saved)
            metrics['independent_review_regressions'] = await exercise_review(f'http://127.0.0.1:{port}', base)
            print(json.dumps({'ok':True,'metrics':metrics},ensure_ascii=False,indent=2))
        finally:
            process.terminate()
            try: process.wait(timeout=15)
            except subprocess.TimeoutExpired: process.kill(); process.wait(timeout=5)


if __name__ == '__main__': asyncio.run(main())
