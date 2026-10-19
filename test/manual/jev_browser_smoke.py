"""Opt-in native TypeSafe + persistent MCP + isolated Chromium acceptance.

Makes potentially billable TypeSafe calls. --graph also uses the configured main
model/factory/middleware. --public adds independent TodoMVC React task trials:
public demo, isolated in-memory app data, no login or real account/business writes.
No credentials are discovered, printed or included in reports. No speedup claim:
measures this bounded helper, not a whole-agent baseline or model-only latency.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from langchain_core.messages import HumanMessage
from playwright.async_api import async_playwright
from tools.jev_browser import make_jev_browser_tools
from utils.mcp_client import create_persistent_mcp_session
import browser_runtime_smoke as fixture

PUBLIC_SITE = 'https://todomvc.com/examples/react/dist/'
LOCAL_PAGE = '''<!doctype html><html><body><h1>Local profile</h1>
<label>Name <input id="name"></label><label>Plan <select id="plan"><option value="free">Free</option><option value="pro">Pro</option></select></label>
<button id="save" type="button">Save locally</button><p id="status">Unsaved</p>
<script>document.querySelector('#save').onclick=async()=>{
 const name=document.querySelector('#name').value,plan=document.querySelector('#plan').value;
 await fetch('/save',{method:'POST',body:JSON.stringify({name,plan})});
 document.querySelector('#status').textContent='Saved '+name+' '+plan;
};</script></body></html>'''


def local_args():
    return {'goal': 'First set Name to Jev Alice; next select Plan Pro; only then click Save locally. Verify the saved Jev Alice pro status.',
            'candidates': [
                {'id': 'fill_name', 'description': 'Fill Name with Jev Alice if the current Name is different.',
                 'action': {'op': 'fill', 'target': '#name', 'value': 'Jev Alice'}},
                {'id': 'select_pro', 'description': 'Only after Name is Jev Alice, select the Pro plan if the current Plan is not pro.',
                 'action': {'op': 'select', 'target': '#plan', 'value': 'pro'}},
                {'id': 'save_profile', 'description': 'Click Save locally only after Name is Jev Alice and Plan is pro.',
                 'action': {'op': 'click', 'target': '#save'}}],
            'success_checks': [{'target': '#status', 'text': 'Saved Jev Alice pro'}], 'max_actions': 3}


def public_args():
    return {'goal': 'Complete Buy milk first, then Pick up bread; leave Review pull request active. Keep the current All filter.',
            'candidates': [
                {'id': 'milk', 'description': 'Mark Buy milk completed if not already checked.',
                 'action': {'op': 'check', 'target': 'li:has(label:text-is("Buy milk")) input.toggle'}},
                {'id': 'bread', 'description': 'Only after Buy milk is checked, mark Pick up bread completed if not already checked.',
                 'action': {'op': 'check', 'target': 'li:has(label:text-is("Pick up bread")) input.toggle'}}],
            'success_checks': [{'target': '.filters a.selected', 'text': 'All', 'match': 'exact'},
                               {'target': 'li.completed:has(label:text-is("Buy milk")) label', 'text': 'Buy milk', 'match': 'exact'},
                               {'target': 'li.completed:has(label:text-is("Pick up bread")) label', 'text': 'Pick up bread', 'match': 'exact'},
                               {'target': '.todo-count', 'text': '1 item left'}],
            'max_actions': 2}


async def local_trial(endpoint, base, saved, graph):
    async with create_persistent_mcp_session(endpoint) as native:
        tools = {t.name: t for t in native}
        await tools['browser_navigate'].ainvoke({'url': base})
        helpers = {t.name: t for t in make_jev_browser_tools(native)}
        assert set(helpers) == {'browser_jev_decide', 'browser_jev_run'}
        decision = await helpers['browser_jev_decide'].ainvoke({'questions': {
            'saved': {'type': 'noul', 'instructions': 'Does the observed page explicitly confirm a successfully saved Jev Alice pro profile?'},
            'next': {'type': 'choice', 'instructions': 'What should happen next for an as-yet-unsaved profile?',
                     'criteria': {'fill_profile': 'Fill in the authorized test name and plan.', 'read_result': 'The correct profile has already been saved; only read its result.'}},
            'progress': {'type': 'score', 'instructions': 'How far along is saving a Jev Alice pro profile?',
                         'criteria': ['Not saved with the requested name and plan.', 'Requested values are entered but not confirmed saved.', 'Explicitly saved Jev Alice pro status is visible.']}}})
        assert decision.get('ok') and not decision['executed'] and not decision['verified'], decision
        started = time.perf_counter()
        if graph:
            from utils.agent_factory import create_browser_agent
            agent = await create_browser_agent(native)
            prompt = ('This is an authorized isolated local-only test. Use browser_jev_run exactly once with these already inspected selectors and exact arguments: '
                      + json.dumps(local_args()) + '. Jev uses the highest-probability option; do not invent confidence thresholds or replay attempted_ids. If Jev hands off, freshly observe and complete only the remaining authorized steps using browser_batch, then read #status. After success report the actually observed result briefly. No credentials, external sites or terminal actions.')
            state = await agent.ainvoke({'messages': [HumanMessage(content=prompt)]},
                {'configurable': {'thread_id': 'jev-smoke-' + uuid.uuid4().hex}, 'recursion_limit': 40})
            messages = state['messages']
            calls = [c for m in messages if m.type == 'ai' for c in m.tool_calls]
            assert sum(c['name'] == 'browser_jev_run' for c in calls) == 1, calls
            results = [m for m in messages if m.type == 'tool' and m.name == 'browser_jev_run']
            assert len(results) == 1
            result = json.loads(results[0].content)
            # Experience summarization is a real additional main-provider path.
            background = [t for t in asyncio.all_tasks() if getattr(t.get_coro(), '__name__', '') == '_run_experience_summarizer']
            if background:
                _, pending = await asyncio.wait(background, timeout=150)
                assert not pending, 'Real background summaries did not finish'
            main_usage = [m.usage_metadata for m in messages if m.type == 'ai']
        else:
            result = await helpers['browser_jev_run'].ainvoke(local_args())
            main_usage = []
        elapsed = time.perf_counter() - started
        if not graph:
            assert result['verified'], result
        assert saved and saved[-1] == {'name': 'Jev Alice', 'plan': 'pro'}, saved
        async with async_playwright() as pw:
            browser = await pw.chromium.connect_over_cdp(endpoint)
            try:
                page = next(p for c in browser.contexts for p in c.pages if p.url.startswith(base))
                status = await page.locator('#status').inner_text()
                assert 'Saved Jev Alice pro' in status
            finally:
                await browser.close()
        return {'ok': True, 'factory_graph': graph, 'seconds': elapsed, 'decision': decision,
                'result': result, 'independent_status': status, 'saved_record': saved[-1], 'main_model_usage': main_usage}


async def public_trial(endpoint, index):
    async with create_persistent_mcp_session(endpoint) as native:
        tools = {t.name: t for t in native}
        await tools['browser_navigate'].ainvoke({'url': PUBLIC_SITE})
        async with async_playwright() as pw:
            browser = await pw.chromium.connect_over_cdp(endpoint)
            try:
                page = next(p for c in browser.contexts for p in c.pages if p.url.startswith(PUBLIC_SITE))
                await page.evaluate('() => localStorage.clear()')
                await page.goto(PUBLIC_SITE, wait_until='domcontentloaded')
                entry = page.get_by_placeholder('What needs to be done?')
                for task in ['Buy milk', 'Pick up bread', 'Review pull request']:
                    await entry.fill(task); await entry.press('Enter')
                assert await page.locator('.todo-list li label').all_text_contents() == ['Buy milk', 'Pick up bread', 'Review pull request']
                helper = next(t for t in make_jev_browser_tools(native) if t.name == 'browser_jev_run')
                started = time.perf_counter()
                result = await helper.ainvoke(public_args())
                elapsed = time.perf_counter() - started
                # Independent direct Playwright DOM oracle, not Jev belief or
                # MCP result prose. This React version does NOT persist data.
                selected = await page.locator('.filters a.selected').inner_text()
                visible = await page.locator('.todo-list li label').all_text_contents()
                rows = page.locator('.todo-list li')
                actual = {}
                for n in range(await rows.count()):
                    row = rows.nth(n)
                    actual[await row.locator('label').inner_text()] = await row.locator('input.toggle').is_checked()
                ok = (result.get('verified') is True and selected == 'All'
                      and set(visible) == {'Buy milk', 'Pick up bread', 'Review pull request'}
                      and actual == {'Buy milk': True, 'Pick up bread': True, 'Review pull request': False})
                return {'trial': index, 'ok': ok, 'seconds': elapsed, 'result': result,
                        'selected_filter': selected, 'visible_items': visible, 'independent_dom_records': actual}
            finally:
                await browser.close()


async def main(args):
    if not os.getenv('TYPESAFE_API_KEY') or os.getenv('DAIBOO_JEV_ENABLED', '').lower() not in {'true', '1'}:
        raise RuntimeError('Explicit DAIBOO_JEV_ENABLED=true and TYPESAFE_API_KEY required')
    if args.graph and not all(os.getenv(n) for n in ('OPENAI_API_KEY', 'OPENAI_BASE_URL', 'OPENAI_MODEL')):
        raise RuntimeError('--graph requires the explicitly authorized main model configuration')
    os.environ.update(DAIBOO_BROWSER_ALLOW_UNSAFE_CODE='false', DAIBOO_BROWSER_SNAPSHOT_MODE='none')
    report = {'requested_model': os.getenv('TYPESAFE_MODEL', 'jev-latest'), 'public_site': PUBLIC_SITE if args.public else None,
              'measurement_scope': 'Bounded helper including browser reads, native TypeSafe calls and actions; setup excluded. Graph local measurement separately includes main agent and summary. No main-model baseline or general speedup claim.',
              'public_data_scope': 'Isolated in-memory React app data; no authenticated production-business writes.', 'public_trials': []}
    async with async_playwright() as pw:
        executable = os.getenv('CHROMIUM_EXECUTABLE') or pw.chromium.executable_path
        if not Path(executable).is_file():
            installed = sorted(Path.home().glob('.cache/ms-playwright/chromium-*/chrome-linux64/chrome'))
            executable = str(installed[-1]) if installed else shutil.which('chromium')
        if not executable:
            raise RuntimeError('Install Chromium first')
    with tempfile.TemporaryDirectory(prefix='daiboo-jev-') as profile, fixture.fixture_server(LOCAL_PAGE) as (base, saved):
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0)); port = sock.getsockname()[1]
        process = subprocess.Popen([executable, '--headless=new', '--no-sandbox', '--no-proxy-server',
            '--disable-dev-shm-usage', '--remote-debugging-address=127.0.0.1', f'--remote-debugging-port={port}',
            f'--user-data-dir={profile}', 'about:blank'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            await fixture.wait_cdp(port, process)
            endpoint = f'http://127.0.0.1:{port}'
            if not args.skip_local:
                report['local'] = await local_trial(endpoint, base, saved, args.graph)
            for index in range(args.trials if args.public else 0):
                trial = await public_trial(endpoint, index + 1)
                report['public_trials'].append(trial)
                if args.report:
                    Path(args.report).write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n')
            report['ok'] = (args.skip_local or report['local']['ok']) and len(report['public_trials']) == (args.trials if args.public else 0) and all(t['ok'] for t in report['public_trials'])
        finally:
            process.terminate()
            try: process.wait(timeout=15)
            except subprocess.TimeoutExpired: process.kill(); process.wait(timeout=5)
            if args.report:
                Path(args.report).write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n')
    print(json.dumps(report, ensure_ascii=False, indent=2))
    assert report['ok'], 'A requested native task did not pass; inspect the real report'


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live', action='store_true', required=True, help='Explicitly permit native provider calls')
    parser.add_argument('--graph', action='store_true')
    parser.add_argument('--public', action='store_true')
    parser.add_argument('--skip-local', action='store_true', help='Run only public trials; requires --public')
    parser.add_argument('--trials', type=int, choices=range(1, 6), default=3)
    parser.add_argument('--report')
    args = parser.parse_args()
    if args.skip_local and (not args.public or args.graph):
        parser.error('--skip-local requires --public and cannot use --graph')
    asyncio.run(main(args))
