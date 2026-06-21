"""Persistent chat history storage for Daiboo web sessions."""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import Any, cast

_HISTORY_LOCK = RLock()


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _default_history_path() -> Path:
    project_root = Path(__file__).resolve().parents[1]
    base_dir = Path(os.getenv("DAIBOO_CHECKPOINT_DIR", str(project_root / "data")))
    return base_dir / "chat_history.json"


def history_path() -> Path:
    """Return the configured chat-history JSON file path."""
    return Path(os.getenv("DAIBOO_CHAT_HISTORY_FILE", str(_default_history_path())))


def _empty_store() -> dict[str, Any]:
    return {"version": 1, "sessions": {}}


def _read_store(path: Path | None = None) -> dict[str, Any]:
    target = path or history_path()
    if not target.exists():
        return _empty_store()
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return _empty_store()
    if not isinstance(data, dict):
        return _empty_store()
    sessions = data.get("sessions")
    if not isinstance(sessions, dict):
        data["sessions"] = {}
    data.setdefault("version", 1)
    return data


def _write_store(data: dict[str, Any], path: Path | None = None) -> None:
    target = path or history_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(data, ensure_ascii=False, indent=2)
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=str(target.parent),
        delete=False,
    ) as tmp:
        tmp.write(payload)
        tmp.write("\n")
        tmp_path = Path(tmp.name)
    tmp_path.replace(target)


def _message_preview(content: str, limit: int = 80) -> str:
    compact = " ".join(str(content or "").split())
    if len(compact) <= limit:
        return compact
    return compact[: limit - 1].rstrip() + "…"


def _ensure_session(store: dict[str, Any], thread_id: str, now: str | None = None) -> dict[str, Any]:
    sessions = store.setdefault("sessions", {})
    now = now or _utc_now_iso()
    session = sessions.get(thread_id)
    if not isinstance(session, dict):
        session = {
            "thread_id": thread_id,
            "title": "新对话",
            "created_at": now,
            "updated_at": now,
            "messages": [],
        }
        sessions[thread_id] = session
    session.setdefault("thread_id", thread_id)
    session.setdefault("title", "新对话")
    session.setdefault("created_at", now)
    session.setdefault("updated_at", now)
    if not isinstance(session.get("messages"), list):
        session["messages"] = []
    return session


def append_chat_message(thread_id: str, role: str, content: str, *, path: Path | None = None) -> dict[str, Any]:
    """Append a user/agent message to a persistent chat session."""
    clean_thread_id = str(thread_id or "default")
    clean_role = str(role or "").strip().lower()
    if clean_role not in {"user", "agent"}:
        raise ValueError("role must be 'user' or 'agent'")

    now = _utc_now_iso()
    with _HISTORY_LOCK:
        store = _read_store(path)
        session = _ensure_session(store, clean_thread_id, now)
        message = {
            "role": clean_role,
            "content": str(content or ""),
            "created_at": now,
        }
        session["messages"].append(message)
        session["updated_at"] = now
        if clean_role == "user" and (not session.get("title") or session.get("title") == "新对话"):
            session["title"] = _message_preview(str(content or ""), 48) or "新对话"
        _write_store(store, path)
        return message


def list_chat_sessions(*, path: Path | None = None) -> list[dict[str, Any]]:
    """List chat sessions with newest-updated first."""
    with _HISTORY_LOCK:
        store = _read_store(path)
    sessions: list[dict[str, Any]] = []
    for thread_id, session in store.get("sessions", {}).items():
        if not isinstance(session, dict):
            continue
        messages = cast(list[Any], session.get("messages") if isinstance(session.get("messages"), list) else [])
        last_message = messages[-1] if messages else None
        sessions.append(
            {
                "thread_id": str(session.get("thread_id") or thread_id),
                "title": str(session.get("title") or "新对话"),
                "created_at": str(session.get("created_at") or ""),
                "updated_at": str(session.get("updated_at") or ""),
                "message_count": len(messages),
                "last_message": _message_preview(last_message.get("content", "") if isinstance(last_message, dict) else ""),
            }
        )
    return sorted(sessions, key=lambda item: item.get("updated_at", ""), reverse=True)


def get_chat_session(thread_id: str, *, path: Path | None = None) -> dict[str, Any] | None:
    """Return a full chat session, including messages."""
    clean_thread_id = str(thread_id or "default")
    with _HISTORY_LOCK:
        store = _read_store(path)
    session = store.get("sessions", {}).get(clean_thread_id)
    if not isinstance(session, dict):
        return None
    messages = cast(list[Any], session.get("messages") if isinstance(session.get("messages"), list) else [])
    return {
        "thread_id": str(session.get("thread_id") or clean_thread_id),
        "title": str(session.get("title") or "新对话"),
        "created_at": str(session.get("created_at") or ""),
        "updated_at": str(session.get("updated_at") or ""),
        "messages": [
            {
                "role": str(msg.get("role") or ""),
                "content": str(msg.get("content") or ""),
                "created_at": str(msg.get("created_at") or ""),
            }
            for msg in messages
            if isinstance(msg, dict)
        ],
    }


def delete_chat_session(thread_id: str, *, path: Path | None = None) -> bool:
    """Delete a persisted chat history session by thread id."""
    clean_thread_id = str(thread_id or "default")
    with _HISTORY_LOCK:
        store = _read_store(path)
        existed = clean_thread_id in store.get("sessions", {})
        if existed:
            del store["sessions"][clean_thread_id]
            _write_store(store, path)
        return existed
