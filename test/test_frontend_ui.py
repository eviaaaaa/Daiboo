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
