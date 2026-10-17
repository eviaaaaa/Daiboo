from pathlib import Path


API_FILE = Path(__file__).resolve().parents[1] / "api.py"


def test_api_exposes_chat_history_routes() -> None:
    api_source = API_FILE.read_text(encoding="utf-8")

    assert '"/chat/sessions"' in api_source
    assert '"/chat/sessions/{thread_id}"' in api_source
    assert "list_chat_sessions_endpoint" in api_source
    assert "get_chat_session_endpoint" in api_source
    assert "delete_chat_session_endpoint" in api_source
    assert "ChatSessionSummary" in api_source
    assert "ChatSessionDetail" in api_source


def test_chat_stream_persists_user_and_agent_messages() -> None:
    api_source = API_FILE.read_text(encoding="utf-8")

    assert 'append_chat_message(request.thread_id, "user", request.message)' in api_source
    assert 'append_chat_message(request.thread_id, "agent", "\\n\\n".join(agent_messages))' in api_source
    assert "agent_messages.append(message_content)" in api_source


async def _stream_fixture_chat(monkeypatch):
    import json
    import api
    from types import SimpleNamespace
    from langchain_core.messages import AIMessage, ToolMessage

    reasoning = AIMessage(content=[{"type": "reasoning", "id": "rs_1",
        "encrypted_content": "opaque-replay", "summary": []}], id="a0")
    answer = AIMessage(content=[{"type": "output_text", "text": "visible answer", "id": "msg_1"}], id="a1")
    tool = ToolMessage(content=[{"type": "output_text", "text": "visible tool result"}],
        id="t1", tool_call_id="c1", name="browser_snapshot", artifact={"private": "opaque-artifact"})
    originals = [m.model_dump() for m in [reasoning, answer, tool]]

    class FixtureAgent:
        async def aget_state(self, config):
            return SimpleNamespace(next=())

        async def astream(self, *args, **kwargs):
            yield {"model": {"messages": [reasoning]}}
            yield {"tools": {"messages": [tool]}}
            yield {"model": {"messages": [answer]}}

    history = []
    monkeypatch.delenv("DAIBOO_DEMO_MODE", raising=False)
    monkeypatch.setattr(api.state, "agent", FixtureAgent(), raising=False)
    monkeypatch.setattr(api, "append_chat_message", lambda *args: history.append(args))
    response = await api.chat(api.ChatRequest(message="question", thread_id="fixture-session"))
    events = [json.loads(part) async for part in response.body_iterator]
    assert [m.model_dump() for m in [reasoning, answer, tool]] == originals
    return events, history


import pytest


@pytest.mark.asyncio
async def test_chat_stream_omits_reasoning_only_empty_message(monkeypatch):
    events, history = await _stream_fixture_chat(monkeypatch)
    assert [e["content"] for e in events if e["type"] == "message"] == ["visible answer"]
    assert history[-1] == ("fixture-session", "agent", "visible answer")


@pytest.mark.asyncio
async def test_chat_tool_display_uses_text_projection_not_message_repr(monkeypatch):
    import json
    events, _ = await _stream_fixture_chat(monkeypatch)
    tools = [e for e in events if e["type"] == "tool"]
    assert len(tools) == 1 and "visible tool result" in tools[0]["content"]
    display = json.dumps(events)
    assert "opaque-artifact" not in display
    assert "opaque-replay" not in display
    assert "output_text" not in tools[0]["content"]
