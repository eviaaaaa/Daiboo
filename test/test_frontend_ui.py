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
