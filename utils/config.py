"""Project configuration helpers."""

from __future__ import annotations

import os
from pathlib import Path


_PORT_ERROR = "PORT must be an integer between 1 and 65535"


def project_root() -> Path:
    return Path(__file__).resolve().parents[1]


def upload_dir() -> Path:
    """Return the server-controlled temporary upload directory."""
    configured = Path((os.getenv("UPLOAD_DIR") or "").strip() or "temp_uploads").expanduser()
    if configured.is_absolute():
        return configured
    return project_root() / configured


def app_host() -> str:
    return (os.getenv("HOST") or "").strip() or "127.0.0.1"


def app_port() -> int:
    raw_port = os.getenv("PORT", "8801")
    try:
        port = int(raw_port)
    except (TypeError, ValueError) as exc:
        raise ValueError(_PORT_ERROR) from exc

    if not 1 <= port <= 65535:
        raise ValueError(_PORT_ERROR)

    return port
