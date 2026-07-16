import importlib


def _reload_mcp_client():
    import sys

    sys.modules.pop("utils.my_browser", None)
    import utils.mcp_client as mcp_client

    return importlib.reload(mcp_client)


def test_mcp_connection_uses_default_cdp_endpoint(monkeypatch):
    monkeypatch.delenv("NPX_COMMAND", raising=False)

    mcp_client = _reload_mcp_client()
    connection = mcp_client._mcp_connection()

    assert connection["args"][connection["args"].index("--cdp-endpoint") + 1] == "http://127.0.0.1:9222"


def test_mcp_connection_builds_default_endpoint_from_debugging_port(monkeypatch):
    monkeypatch.setenv("DEBUGGING_PORT", "9333")

    mcp_client = _reload_mcp_client()
    connection = mcp_client._mcp_connection()

    assert connection["args"][connection["args"].index("--cdp-endpoint") + 1] == "http://127.0.0.1:9333"


def test_mcp_connection_treats_blank_npx_command_as_unset(monkeypatch):
    monkeypatch.setenv("NPX_COMMAND", "   ")
    monkeypatch.setattr("shutil.which", lambda command: f"/usr/bin/{command}" if command == "npx" else None)

    mcp_client = _reload_mcp_client()
    connection = mcp_client._mcp_connection()

    assert connection["command"] == "/usr/bin/npx"


def test_mcp_connection_omits_blank_explicit_cdp_endpoint(monkeypatch):
    monkeypatch.setenv("DEBUGGING_PORT", "9333")

    mcp_client = _reload_mcp_client()
    connection = mcp_client._mcp_connection("   ")

    assert connection["args"][connection["args"].index("--cdp-endpoint") + 1] == "http://127.0.0.1:9333"


def test_mcp_connection_pins_verified_playwright_mcp_version(monkeypatch):
    monkeypatch.delenv("PLAYWRIGHT_MCP_VERSION", raising=False)

    mcp_client = _reload_mcp_client()
    connection = mcp_client._mcp_connection()

    assert connection["args"][0] == "@playwright/mcp@0.0.78"
    assert "@latest" not in connection["args"][0]


def test_mcp_connection_allows_explicit_playwright_mcp_version(monkeypatch):
    monkeypatch.setenv("PLAYWRIGHT_MCP_VERSION", "0.0.77")

    mcp_client = _reload_mcp_client()
    connection = mcp_client._mcp_connection()

    assert connection["args"][0] == "@playwright/mcp@0.0.77"
