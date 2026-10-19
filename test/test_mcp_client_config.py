import importlib


def _reload_mcp_client():
    import sys

    sys.modules.pop("utils.my_browser", None)
    import utils.mcp_client as mcp_client

    return importlib.reload(mcp_client)


def test_mcp_connection_uses_default_cdp_endpoint(monkeypatch):
    monkeypatch.delenv("NPX_COMMAND", raising=False)
    monkeypatch.delenv("DEBUGGING_PORT", raising=False)

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

    assert connection["args"][0] == "@playwright/mcp@0.0.83"
    assert "@latest" not in connection["args"][0]


def test_mcp_connection_allows_explicit_playwright_mcp_version(monkeypatch):
    monkeypatch.setenv("PLAYWRIGHT_MCP_VERSION", "0.0.77")

    mcp_client = _reload_mcp_client()
    connection = mcp_client._mcp_connection()

    assert connection["args"][0] == "@playwright/mcp@0.0.77"


def test_mcp_connection_discloses_snapshots_only_on_request(monkeypatch):
    monkeypatch.delenv('DAIBOO_BROWSER_SNAPSHOT_MODE', raising=False)
    connection = _reload_mcp_client()._mcp_connection()
    assert connection['args'][connection['args'].index('--snapshot-mode') + 1] == 'none'


def test_mcp_snapshot_mode_can_restore_full(monkeypatch):
    monkeypatch.setenv('DAIBOO_BROWSER_SNAPSHOT_MODE', 'full')
    connection = _reload_mcp_client()._mcp_connection()
    assert connection['args'][connection['args'].index('--snapshot-mode') + 1] == 'full'


def test_mcp_caps_are_configurable_and_validated(monkeypatch):
    import pytest
    monkeypatch.setenv('PLAYWRIGHT_MCP_CAPS', 'pdf,vision')
    connection = _reload_mcp_client()._mcp_connection()
    assert '--caps=pdf,vision' in connection['args']
    monkeypatch.setenv('PLAYWRIGHT_MCP_CAPS', 'jev')
    with pytest.raises(ValueError, match='PLAYWRIGHT_MCP_CAPS'):
        _reload_mcp_client()._mcp_connection()


def test_mcp_hides_rce_equivalent_tools_by_default(monkeypatch):
    from types import SimpleNamespace
    monkeypatch.delenv('DAIBOO_BROWSER_ALLOW_UNSAFE_CODE', raising=False)
    module = _reload_mcp_client()
    raw = [SimpleNamespace(name=n, args={}) for n in ['browser_snapshot', 'browser_run_code_unsafe']]
    tools = module.MCPToolList(raw, snapshot_mode='none')
    assert [t.name for t in tools] == ['browser_snapshot']
    assert tools.all_tools['browser_run_code_unsafe'] is raw[1]


def test_mcp_unsafe_code_is_only_exposed_by_explicit_opt_in(monkeypatch):
    from types import SimpleNamespace
    monkeypatch.setenv('DAIBOO_BROWSER_ALLOW_UNSAFE_CODE', 'true')
    module = _reload_mcp_client()
    raw = [SimpleNamespace(name='browser_run_code_unsafe', args={})]
    assert list(module.MCPToolList(raw, snapshot_mode='none')) == raw
