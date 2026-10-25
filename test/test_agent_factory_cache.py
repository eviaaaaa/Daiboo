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


@pytest.mark.asyncio
async def test_create_browser_agent_adds_openai_fallback_middleware(monkeypatch):
    created = {}
    primary_model = object()
    fallback_model = object()

    class FakeAgent:
        nodes = {}

    def fake_create_agent(**kwargs):
        created.update(kwargs)
        return FakeAgent()

    def fake_create_model(*, env_prefix="OPENAI", **_kwargs):
        return fallback_model if env_prefix == "OPENAI_FALLBACK" else primary_model

    monkeypatch.setenv("OPENAI_MODEL", "primary-model")
    monkeypatch.setenv("OPENAI_FALLBACK_MODEL", "fallback-model")
    monkeypatch.setattr(agent_factory.agents, "create_agent", fake_create_agent)
    monkeypatch.setattr(agent_factory, "get_agent_tools", lambda tools, helper: list(tools))
    monkeypatch.setattr(agent_factory, "is_openai_compatible_configured", lambda _prefix="OPENAI": True)
    monkeypatch.setattr(agent_factory, "create_openai_compatible_model", fake_create_model)
    monkeypatch.setattr(agent_factory, "ContextManagerMiddleware", lambda model: ("context", model))
    monkeypatch.setattr(agent_factory, "HumanInTheLoopMiddleware", lambda **kwargs: ("hitl", kwargs))
    monkeypatch.setattr(agent_factory, "ModelFallbackMiddleware", lambda model: ("fallback", model))
    monkeypatch.setattr(agent_factory, "make_diff_middleware", lambda tools: ("diff", id(tools)))

    await agent_factory.create_browser_agent([object()])

    assert created["model"] is primary_model
    assert ("fallback", fallback_model) in created["middleware"]
