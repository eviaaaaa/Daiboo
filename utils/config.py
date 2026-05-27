"""Project configuration helpers."""

from __future__ import annotations

import os
from pathlib import Path


def project_root() -> Path:
    return Path(__file__).resolve().parents[1]


def upload_dir() -> Path:
    """Return the server-controlled temporary upload directory."""
    return Path(os.getenv("UPLOAD_DIR", project_root() / "temp_uploads")).expanduser()


def app_host() -> str:
    return os.getenv("HOST", "127.0.0.1")


def app_port() -> int:
    return int(os.getenv("PORT", "8801"))
