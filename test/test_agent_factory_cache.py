import pytest

from utils import agent_factory


@pytest.mark.asyncio
async def test_create_browser_agent_does_not_reuse_session_bound_agent(monkeypatch):
    created = []

    class FakeAgent:
        nodes = {}

    def fake_create_agent(**kwargs):
        created.append(kwargs)
        return FakeAgent()

    monkeypatch.setattr(agent_factory.agents, "create_agent", fake_create_agent)
    monkeypatch.setattr(agent_factory, "get_agent_tools", lambda tools, helper: list(tools))
    monkeypatch.setattr(agent_factory, "is_openai_compatible_configured", lambda: False)
    monkeypatch.setattr(agent_factory, "create_qwen_model", lambda **kwargs: object())
    monkeypatch.setattr(agent_factory, "ContextManagerMiddleware", lambda model: object())
    monkeypatch.setattr(agent_factory, "HumanInTheLoopMiddleware", lambda **kwargs: object())
    monkeypatch.setattr(agent_factory, "make_diff_middleware", lambda tools: ("diff", id(tools)))
    monkeypatch.setattr(agent_factory, "skills_summary", lambda: "- fixture-skill: Load only for fixture work", raising=False)

    first_tools = [object()]
    second_tools = [object()]
    first_checkpointer = object()
    second_checkpointer = object()

    first = await agent_factory.create_browser_agent(first_tools, checkpointer=first_checkpointer)
    second = await agent_factory.create_browser_agent(second_tools, checkpointer=second_checkpointer)

    assert first is not second
    assert len(created) == 2
    assert created[0]["checkpointer"] is first_checkpointer
    assert created[1]["checkpointer"] is second_checkpointer
    assert "fixture-skill: Load only for fixture work" in created[0]["system_prompt"]
    assert created[0]["system_prompt"] == created[1]["system_prompt"]


@pytest.mark.asyncio
async def test_openai_agent_does_not_forward_qwen_default_or_temperature(monkeypatch):
    calls = []
    openai_model = object()

    class FakeAgent:
        nodes = {}

    def create_model(**kwargs):
        calls.append(kwargs)
        return openai_model

    monkeypatch.delenv("OPENAI_MODEL", raising=False)
    monkeypatch.setattr(agent_factory.agents, "create_agent", lambda **kwargs: FakeAgent())
    monkeypatch.setattr(agent_factory, "get_agent_tools", lambda tools, helper: list(tools))
    monkeypatch.setattr(agent_factory, "is_openai_compatible_configured", lambda: True)
    monkeypatch.setattr(agent_factory, "create_openai_compatible_model", create_model)
    monkeypatch.setattr(agent_factory, "ContextManagerMiddleware", lambda model: object())
    monkeypatch.setattr(agent_factory, "HumanInTheLoopMiddleware", lambda **kwargs: object())
    monkeypatch.setattr(agent_factory, "make_diff_middleware", lambda tools: object())
    await agent_factory.create_browser_agent([])
    assert calls == [{"request_timeout": 5000}]


@pytest.mark.asyncio
async def test_factory_wires_session_bound_batch_without_exposing_code(monkeypatch):
    from langchain_core.tools import StructuredTool
    from utils.mcp_client import MCPToolList

    async def backend(code: str) -> dict:
        assert "JSON.parse" in code
        return {"ok": True, "completed": 1, "verified": False, "reads": []}

    monkeypatch.delenv("DAIBOO_BROWSER_ALLOW_UNSAFE_CODE", raising=False)
    session_tools = MCPToolList([
        StructuredTool.from_function(coroutine=backend, name="browser_run_code_unsafe", description="Native backend")
    ], snapshot_mode="none")
    tools = {tool.name: tool for tool in agent_factory.get_agent_tools(session_tools)}
    assert "browser_run_code_unsafe" not in tools
    assert "browser_batch" in tools and "browser_runtime_info" in tools
    info = await tools["browser_runtime_info"].ainvoke({})
    assert info["batch_available"] is True
    result = await tools["browser_batch"].ainvoke({"steps": [{"op": "read_text", "target": "#status"}]})
    assert result["ok"] is True and result["completed"] == 1
