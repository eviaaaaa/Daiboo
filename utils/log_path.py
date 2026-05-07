"""日志/归档文件命名辅助。"""
from __future__ import annotations

import re
from datetime import datetime


def sanitize_path_fragment(value: str, fallback: str = "unknown") -> str:
    """把任意字符串压缩为适合文件名的片段。"""
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", (value or "").strip())
    cleaned = cleaned.strip("-._")
    return cleaned or fallback


def short_session_fragment(session_id: str | None, fallback: str = "session") -> str:
    """生成短 session 片段，便于从文件名快速定位来源。"""
    cleaned = sanitize_path_fragment(session_id or "", fallback=fallback)
    return cleaned[:24]


def build_timestamped_filename(prefix: str, session_id: str | None = None, suffix: str = ".txt") -> str:
    """生成带日期和 session 片段的文件名。"""
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    prefix_part = sanitize_path_fragment(prefix, fallback="log")
    session_part = short_session_fragment(session_id)
    return f"{prefix_part}_{stamp}_{session_part}{suffix}"
