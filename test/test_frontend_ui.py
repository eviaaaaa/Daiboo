from pathlib import Path


FRONTEND_INDEX = Path(__file__).resolve().parents[1] / "frontend" / "index.html"


def _frontend_html() -> str:
    return FRONTEND_INDEX.read_text(encoding="utf-8")


def test_frontend_api_base_uses_same_origin_by_default():
    html = _frontend_html()

    assert "const API_BASE = window.location.origin" in html


def test_frontend_has_linear_inspired_shell_styles():
    html = _frontend_html()

    assert "app-shell" in html
    assert "linear-panel" in html
    assert "linear-card" in html


def test_frontend_secondary_views_use_dark_console_surfaces():
    html = _frontend_html()

    assert "rag-workbench" in html
    assert "tools-workbench" in html
    assert "data-surface" in html
    assert "tool-card" in html
    assert "text-gray-800" not in html
    assert "class=\"bg-white" not in html
    assert " class=\"bg-white" not in html


def test_frontend_has_responsive_mobile_navigation():
    html = _frontend_html()

    assert "mobile-tab-bar" in html
    assert "desktop-sidebar" in html
    assert "pb-24" in html
    assert "hidden md:flex" in html
    assert "md:hidden" in html
    assert "@click=\"currentTab = 'chat'\"" in html
    assert "@click=\"currentTab = 'upload'\"" in html
    assert "@click=\"fetchTools(); currentTab = 'tools'\"" in html


def test_frontend_markdown_is_readable_in_dark_agent_messages():
    html = _frontend_html()

    assert "markdown-body" in html
    assert ".markdown-body pre" in html
    assert ".markdown-body code" in html
    assert ".markdown-body a" in html
    assert "overflow-x: auto" in html
    assert "JetBrains Mono" in html
    assert "prose prose-sm" not in html


def test_frontend_tools_view_has_loading_error_and_empty_states():
    html = _frontend_html()

    assert "isLoadingTools" in html
    assert "toolsError" in html
    assert "tools-empty-state" in html
    assert "tools-error-state" in html
    assert "tools-loading-state" in html
    assert "重新加载" in html
    assert "throw new Error(err.detail || '工具列表接口调用失败')" in html
