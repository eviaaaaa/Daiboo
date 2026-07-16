from __future__ import annotations

from pathlib import Path, PurePath, PureWindowsPath
from uuid import uuid4


ALLOWED_UPLOAD_EXTENSIONS = frozenset({".pdf", ".doc", ".docx", ".md", ".txt"})


def _client_basename(client_filename: str) -> str:
    """Return a filename-only display name for POSIX or Windows client paths.

    Browsers may submit either a bare filename or a platform-specific path
    segment.  On Linux, ``PurePath("..\\..\\secret.txt").name`` treats
    backslashes as literal characters, so normalize both path syntaxes before
    deriving the user-facing name.
    """
    posix_name = PurePath(client_filename).name
    windows_name = PureWindowsPath(client_filename).name
    return PurePath(posix_name).name if len(posix_name) <= len(windows_name) else windows_name


def build_safe_upload_path(upload_dir: Path, client_filename: str) -> tuple[str, Path]:
    """返回展示文件名和服务端控制的安全文件路径。"""
    raw_name = (client_filename or "").strip()
    if not raw_name:
        raise ValueError("File name is required")

    display_name = _client_basename(raw_name)
    if display_name in {"", ".", ".."}:
        raise ValueError("Invalid file name")

    suffix = "".join(ch for ch in Path(display_name).suffix.lower() if ch.isalnum() or ch == ".")
    stored_name = f"{uuid4().hex}{suffix}"

    upload_root = upload_dir.resolve()
    target_path = (upload_root / stored_name).resolve()
    target_path.relative_to(upload_root)

    return display_name, target_path
