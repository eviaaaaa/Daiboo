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
