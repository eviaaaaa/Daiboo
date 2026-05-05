"""tools/web_observe_tool 与 _simphtml/* 的单元测试。

只测纯 Python 部分（post_process / diff / observer 的字符串构造）。
依赖运行中浏览器的真集成测试见末尾的 @pytest.mark.integration 用例，
默认跳过；需要时设置 RUN_BROWSER_INTEGRATION=1 启用。
"""
from __future__ import annotations

import json
import os

import pytest
from bs4 import BeautifulSoup

from tools._simphtml.post_process import optimize_html_for_tokens, smart_truncate
from tools._simphtml.diff import find_changed_elements
from tools._simphtml.observer import (
    build_evaluate_function,
    normalize_evaluate_result,
    OPTHTML_JS,
)


# ── post_process ─────────────────────────────────────────────────


def test_optimize_html_strips_style_attribute():
    html = '<div style="color:red"><p>hello</p></div>'
    soup = optimize_html_for_tokens(html)
    out = str(soup)
    assert "style" not in out
    assert "<p>hello</p>" in out


def test_optimize_html_replaces_long_href():
    html = '<a href="https://example.com/very/long/path/over/30/chars/x">link</a>'
    out = str(optimize_html_for_tokens(html))
    assert '__link__' in out
    assert 'example.com' not in out


def test_optimize_html_replaces_data_image_src():
    html = '<img src="data:image/png;base64,AAAA" />'
    out = str(optimize_html_for_tokens(html))
    assert '__img__' in out
    assert 'base64' not in out


def test_optimize_html_replaces_long_action():
    html = '<form action="/login/x/y/z/very/long/path/over/30">x</form>'
    out = str(optimize_html_for_tokens(html))
    assert '__url__' in out


def test_optimize_html_truncates_long_value():
    long_value = 'a' * 200
    html = f'<input value="{long_value}" />'
    out = str(optimize_html_for_tokens(html))
    assert ' ...' in out
    assert long_value not in out


def test_optimize_html_clears_svg_keeps_tag():
    html = '<svg viewBox="0 0 10 10"><path d="M0 0"/></svg>'
    out = str(optimize_html_for_tokens(html))
    assert '<svg></svg>' in out


def test_optimize_html_drops_data_v_vue_artifact():
    html = '<div data-v-12345="" data-track-id="x">hi</div>'
    out = str(optimize_html_for_tokens(html))
    assert 'data-v-12345' not in out
    assert 'data-track-id' in out  # short data-* preserved


def test_optimize_html_keeps_form_attrs():
    """白名单内的关键 attribute 必须保留，否则 LLM 看不到当前状态。"""
    html = (
        '<input type="text" name="email" placeholder="Enter" '
        'value="me@x.com" required="" />'
    )
    out = str(optimize_html_for_tokens(html))
    for keyword in ('type="text"', 'name="email"', 'placeholder="Enter"',
                    'value="me@x.com"', 'required'):
        assert keyword in out, f'缺失 {keyword}: {out}'


# ── smart_truncate ───────────────────────────────────────────────


def test_smart_truncate_under_budget_unchanged():
    html = '<div>' + ('x' * 500) + '</div>'
    soup = BeautifulSoup(html, 'html.parser')
    out = smart_truncate(soup, 10000)
    assert len(str(out)) == len(html)


def test_smart_truncate_over_budget_shrinks():
    html = '<div>' + ('<p>' + 'y' * 200 + '</p>') * 100 + '</div>'
    soup = BeautifulSoup(html, 'html.parser')
    out = smart_truncate(soup, 1000)
    rendered = str(out)
    assert len(rendered) < len(html)
    assert len(rendered) <= 5000  # 应该能比较接近预算（不一定刚好 1000）


def test_smart_truncate_protects_fake_element_marker():
    """cutlist 留下的 [FAKE ELEMENT] 提示标签必须保留。"""
    html = (
        '<div>'
        + ('<p>' + 'z' * 100 + '</p>') * 50
        + '<div>[FAKE ELEMENT] 47 more items hidden</div>'
        '</div>'
    )
    soup = BeautifulSoup(html, 'html.parser')
    out = smart_truncate(soup, 800)
    assert '[FAKE ELEMENT]' in str(out)


# ── diff ────────────────────────────────────────────────────────


def test_diff_detects_added_node():
    before = '<div><p>hello</p></div>'
    after = '<div><p>hello</p><span class="toast">submitted</span></div>'
    res = find_changed_elements(before, after)
    assert res['changed'] >= 1
    assert 'toast' in res.get('top_change', '')


def test_diff_no_change_returns_zero():
    html = '<div><p>x</p></div>'
    res = find_changed_elements(html, html)
    assert res['changed'] == 0
    assert 'top_change' not in res


def test_diff_handles_text_change():
    before = '<div><p>hello</p></div>'
    after = '<div><p>goodbye</p></div>'
    res = find_changed_elements(before, after)
    assert res['changed'] >= 1
    assert 'goodbye' in res.get('top_change', '')


def test_diff_top_change_truncates_at_2000():
    before = '<div></div>'
    after = '<div><p>' + 'x' * 5000 + '</p></div>'
    res = find_changed_elements(before, after)
    top = res.get('top_change', '')
    assert '[TRUNCATED]' in top
    assert len(top) <= 2050  # 2000 + suffix


def test_diff_handles_empty_inputs():
    assert find_changed_elements('', '<div></div>')['changed'] == 0
    assert find_changed_elements('<div></div>', '')['changed'] == 0


# ── observer 字符串构造 ──────────────────────────────────────────


def test_opthtml_js_loaded_with_function_def():
    """模块加载时 opthtml.js 字符串非空且是有效的 JS function 定义。"""
    assert OPTHTML_JS
    assert OPTHTML_JS.lstrip().startswith('function optHTML')
    # 跨 iframe 内联是核心能力，必须在 JS 中
    assert 'iframe' in OPTHTML_JS
    # Shadow DOM 穿透
    assert 'shadowRoot' in OPTHTML_JS
    # elementFromPoint 真值
    assert 'elementFromPoint' in OPTHTML_JS


def test_build_evaluate_function_default_text_only_false():
    fn = build_evaluate_function(text_only=False)
    assert fn.startswith('() => {')
    assert fn.endswith('}')
    assert 'optHTML(false)' in fn
    assert 'optHTML(true)' not in fn


def test_build_evaluate_function_text_only_true():
    fn = build_evaluate_function(text_only=True)
    assert 'optHTML(true)' in fn
    assert 'optHTML(false)' not in fn


# ── normalize_evaluate_result ────────────────────────────────────


def test_normalize_evaluate_str():
    assert normalize_evaluate_result('<div>x</div>') == '<div>x</div>'


def test_normalize_evaluate_dict_with_value_key():
    assert normalize_evaluate_result({'value': '<div>x</div>'}) == '<div>x</div>'


def test_normalize_evaluate_nested_dict():
    assert normalize_evaluate_result({'result': {'value': 'hi'}}) == 'hi'


def test_normalize_evaluate_json_string():
    raw = json.dumps({'result': 'inner'})
    assert normalize_evaluate_result(raw) == 'inner'


def test_normalize_evaluate_list_of_text_blocks():
    raw = [{'type': 'text', 'text': 'part1'}, {'type': 'text', 'text': 'part2'}]
    assert 'part1' in normalize_evaluate_result(raw)
    assert 'part2' in normalize_evaluate_result(raw)


def test_normalize_evaluate_none_returns_empty():
    assert normalize_evaluate_result(None) == ''


# ── 集成测试：需要真浏览器 ─────────────────────────────────────────


@pytest.mark.skipif(
    os.getenv('RUN_BROWSER_INTEGRATION', '') != '1',
    reason='需要运行中的 Chrome + MCP 会话；设置 RUN_BROWSER_INTEGRATION=1 启用',
)
@pytest.mark.asyncio
async def test_web_observe_integration_basic():
    """端到端：在真 MCP 会话上跑一次 web_observe，至少能拿回非空 HTML。"""
    from utils.my_browser import ensure_browser_running
    from utils.mcp_client import create_persistent_mcp_session
    from tools.web_observe_tool import WebObserveTool

    await ensure_browser_running()
    async with create_persistent_mcp_session() as mcp_tools:
        # 先 navigate 到一个简单页面
        nav = next(t for t in mcp_tools if t.name == 'browser_navigate')
        await nav.ainvoke({'url': 'https://example.com'})

        tool = WebObserveTool(mcp_tools=list(mcp_tools))
        result = await tool._arun(text_only=False, max_chars=10000)

        assert result['ok'] is True, result
        assert result['mode'] == 'html'
        assert result['char_count'] > 0
        assert 'Example Domain' in result['content']
