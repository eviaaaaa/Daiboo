from pathlib import Path
import importlib.util


MODULE_PATH = Path(__file__).resolve().parents[1] / "utils" / "chat_history.py"
spec = importlib.util.spec_from_file_location("daiboo_chat_history_for_test", MODULE_PATH)
assert spec is not None and spec.loader is not None
chat_history = importlib.util.module_from_spec(spec)
spec.loader.exec_module(chat_history)

append_chat_message = chat_history.append_chat_message
delete_chat_session = chat_history.delete_chat_session
get_chat_session = chat_history.get_chat_session
list_chat_sessions = chat_history.list_chat_sessions


def test_chat_history_appends_lists_and_loads_session(tmp_path: Path) -> None:
    history_file = tmp_path / "chat_history.json"

    append_chat_message("session-a", "user", "请打开示例网站", path=history_file)
    append_chat_message("session-a", "agent", "已经打开。", path=history_file)

    sessions = list_chat_sessions(path=history_file)
    assert len(sessions) == 1
    assert sessions[0]["thread_id"] == "session-a"
    assert sessions[0]["title"] == "请打开示例网站"
    assert sessions[0]["message_count"] == 2
    assert sessions[0]["last_message"] == "已经打开。"

    session = get_chat_session("session-a", path=history_file)
    assert session is not None
    assert [msg["role"] for msg in session["messages"]] == ["user", "agent"]
    assert session["messages"][0]["content"] == "请打开示例网站"
    assert session["messages"][1]["content"] == "已经打开。"


def test_chat_history_lists_newest_session_first(tmp_path: Path) -> None:
    history_file = tmp_path / "chat_history.json"

    append_chat_message("old-session", "user", "旧会话", path=history_file)
    append_chat_message("new-session", "user", "新会话", path=history_file)

    sessions = list_chat_sessions(path=history_file)
    assert [session["thread_id"] for session in sessions] == ["new-session", "old-session"]


def test_chat_history_delete_session(tmp_path: Path) -> None:
    history_file = tmp_path / "chat_history.json"

    append_chat_message("session-a", "user", "hello", path=history_file)

    assert delete_chat_session("session-a", path=history_file) is True
    assert get_chat_session("session-a", path=history_file) is None
    assert delete_chat_session("session-a", path=history_file) is False
