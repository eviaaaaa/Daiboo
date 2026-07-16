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
