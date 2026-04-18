from __future__ import annotations

from pathlib import Path, PurePath
from uuid import uuid4


def build_safe_upload_path(upload_dir: Path, client_filename: str) -> tuple[str, Path]:
    """Return a display name plus a server-controlled safe file path."""
    raw_name = (client_filename or "").strip()
    if not raw_name:
        raise ValueError("File name is required")

    display_name = PurePath(raw_name).name
    if display_name in {"", ".", ".."}:
        raise ValueError("Invalid file name")

    suffix = "".join(ch for ch in Path(display_name).suffix.lower() if ch.isalnum() or ch == ".")
    stored_name = f"{uuid4().hex}{suffix}"

    upload_root = upload_dir.resolve()
    target_path = (upload_root / stored_name).resolve()
    target_path.relative_to(upload_root)

    return display_name, target_path
