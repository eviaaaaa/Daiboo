import importlib.util
import shutil
from pathlib import Path
from uuid import uuid4

import pytest


def _load_upload_paths_module():
    module_path = Path(__file__).resolve().parents[1] / "utils" / "upload_paths.py"
    spec = importlib.util.spec_from_file_location("test_upload_paths_module", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def local_upload_dir() -> Path:
    root = Path(__file__).resolve().parents[1] / ".test-temp"
    root.mkdir(exist_ok=True)
    path = root / uuid4().hex
    path.mkdir()
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)


def test_build_safe_upload_path_uses_server_generated_name(local_upload_dir: Path) -> None:
    module = _load_upload_paths_module()
    display_name, file_path = module.build_safe_upload_path(local_upload_dir, "report.final.PDF")

    assert display_name == "report.final.PDF"
    assert file_path.parent == local_upload_dir.resolve()
    assert file_path.suffix == ".pdf"
    assert file_path.name != display_name


def test_build_safe_upload_path_neutralizes_client_path_segments(local_upload_dir: Path) -> None:
    module = _load_upload_paths_module()
    display_name, file_path = module.build_safe_upload_path(local_upload_dir, "..\\..\\secrets.txt")

    assert display_name == "secrets.txt"
    assert file_path.parent == local_upload_dir.resolve()
    file_path.relative_to(local_upload_dir.resolve())


@pytest.mark.parametrize("filename", ["", "   ", ".", ".."])
def test_build_safe_upload_path_rejects_invalid_names(local_upload_dir: Path, filename: str) -> None:
    module = _load_upload_paths_module()
    with pytest.raises(ValueError):
        module.build_safe_upload_path(local_upload_dir, filename)
