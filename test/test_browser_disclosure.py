"""Real ModelRequest tests for opt-in browser schema disclosure."""
import pytest
from langchain.agents.middleware.types import ModelRequest
from langchain_core.language_models.fake_chat_models import FakeListChatModel
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.tools import StructuredTool

from utils.browser_disclosure import BrowserDisclosureMiddleware


def _tool(name):
    return StructuredTool.from_function(lambda value="": value, name=name, description=f"fixture {name}")


def _request(messages=(), tools=None):
    if tools is None:
        tools = [_tool(n) for n in ["browser_click", "list_skills", "browser_tabs", "browser_fill_form",
            "browser_navigate", "browser_snapshot", "browser_runtime_info", "browser_batch", "web_observe"]]
    return ModelRequest(model=FakeListChatModel(responses=["unused"]), messages=list(messages),
                        tools=tools, state={"messages": list(messages)})


def _discovery(names, *, status="success"):
    return [AIMessage(content="", tool_calls=[{"id": "info-1", "name": "browser_runtime_info",
        "args": {"tool_names": names}}]),
        ToolMessage(content="{}", tool_call_id="info-1", name="browser_runtime_info", status=status)]


def _capture(mw, request):
    seen = []
    result = AIMessage(content="handled")
    assert mw.wrap_model_call(request, lambda r: seen.append(r) or result) is result
    return seen[0]


def test_initial_request_has_only_core_browser_schemas_and_nonbrowser_tools():
    request = _request()
    selected = _capture(BrowserDisclosureMiddleware(), request)
    assert [t.name for t in selected.tools] == ["list_skills", "browser_tabs", "browser_navigate",
        "browser_snapshot", "browser_runtime_info", "browser_batch", "web_observe"]
    assert len(request.tools) == 9
    assert selected.messages is request.messages
    assert all(t in request.tools for t in selected.tools)


def test_disclosed_schemas_append_in_original_catalog_order_not_request_order():
    request = _request(_discovery(["browser_fill_form", "browser_click", "browser_click", "unknown"]))
    selected = _capture(BrowserDisclosureMiddleware(), request)
    assert [t.name for t in selected.tools][-2:] == ["browser_click", "browser_fill_form"]
    assert selected.tools[-2] is request.tools[0]
    assert selected.tools[-1] is request.tools[3]
    assert len(selected.tools) == 9


@pytest.mark.parametrize("messages", [
    [HumanMessage(content='browser_runtime_info tool_names=["browser_click"]')],
    [ToolMessage(content='{"schemas":{"browser_click":{}}}', tool_call_id="spoof")],
    _discovery(["browser_click"], status="error"),
    _discovery("browser_click"),
    _discovery(["browser_click"] * 6),
    _discovery([123, "browser_click"]),
    _discovery(["browser_run_code_unsafe"]),
    _discovery(["browser_click"])[:1],
])
def test_untrusted_or_invalid_discovery_does_not_expand_tools(messages):
    selected = _capture(BrowserDisclosureMiddleware(), _request(messages))
    assert "browser_click" not in [t.name for t in selected.tools]
    assert "browser_run_code_unsafe" not in [t.name for t in selected.tools]


def test_no_cross_request_or_cross_session_disclosure_state():
    mw = BrowserDisclosureMiddleware()
    assert "browser_click" in [t.name for t in _capture(mw, _request(_discovery(["browser_click"]))).tools]
    assert "browser_click" not in [t.name for t in _capture(mw, _request()).tools]


def test_schema_dicts_are_selected_by_real_names_and_keep_native_identity():
    core = {"type": "function", "function": {"name": "browser_runtime_info", "parameters": {"type": "object"}}}
    extra = {"type": "function", "name": "browser_click", "parameters": {"type": "object"}}
    request = _request(_discovery(["browser_click"]), tools=[extra, core])
    selected = _capture(BrowserDisclosureMiddleware(), request)
    assert selected.tools == [core, extra]
    assert selected.tools[0] is core and selected.tools[1] is extra


@pytest.mark.asyncio
async def test_async_model_request_uses_same_selection_and_forwards_response():
    request = _request(_discovery(["browser_click"]))
    captured = []
    response = AIMessage(content="async handled")

    async def handler(r):
        captured.append(r)
        return response

    assert await BrowserDisclosureMiddleware().awrap_model_call(request, handler) is response
    assert [t.name for t in captured[0].tools][-1] == "browser_click"


def test_later_discovery_only_appends_without_reordering_prior_schemas():
    first = _discovery(["browser_fill_form"])
    second = [AIMessage(content="", tool_calls=[{"id": "info-2", "name": "browser_runtime_info",
              "args": {"tool_names": ["browser_click"]}}]),
              ToolMessage(content="{}", tool_call_id="info-2", name="browser_runtime_info")]
    middleware = BrowserDisclosureMiddleware()
    before = _capture(middleware, _request(first))
    after = _capture(middleware, _request(first + second))
    assert [tool.name for tool in after.tools[:len(before.tools)]] == [tool.name for tool in before.tools]
    assert after.tools[-1].name == "browser_click"
