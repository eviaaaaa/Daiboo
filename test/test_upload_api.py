from io import BytesIO
from types import SimpleNamespace

import pytest
from fastapi import HTTPException, UploadFile

import api
from rag.document_rag_pgvector import _serialize_rag_document


def _upload(filename: str, content: bytes) -> UploadFile:
    return UploadFile(filename=filename, file=BytesIO(content))


@pytest.mark.asyncio
async def test_upload_preserves_display_name_hides_temp_path_and_cleans_file(monkeypatch, tmp_path):
    captured = {}

    def fake_index(paths, *, source_names, include_source_paths):
        captured["paths"] = paths
        captured["source_names"] = source_names
        captured["include_source_paths"] = include_source_paths
        assert paths[0].exists()
        return {"files": [], "total_parents": 2, "total_children": 4}

    monkeypatch.setattr(api, "upload_dir", lambda: tmp_path)
    monkeypatch.setattr(api, "save_document_to_pgvector", fake_index)

    result = await api.upload_document(_upload("Original Report.TXT", b"hello"))

    stored_path = captured["paths"][0]
    assert result["filename"] == "Original Report.TXT"
    assert captured["source_names"] == {stored_path: "Original Report.TXT"}
    assert captured["include_source_paths"] is False
    assert not stored_path.exists()


@pytest.mark.asyncio
async def test_upload_rejects_unsupported_extension_without_writing(monkeypatch, tmp_path):
    monkeypatch.setattr(api, "upload_dir", lambda: tmp_path)

    with pytest.raises(HTTPException) as exc_info:
        await api.upload_document(_upload("payload.bin", b"data"))

    assert exc_info.value.status_code == 415
    assert list(tmp_path.iterdir()) == []


@pytest.mark.asyncio
async def test_upload_rejects_oversized_file_and_removes_partial_file(monkeypatch, tmp_path):
    monkeypatch.setattr(api, "upload_dir", lambda: tmp_path)
    monkeypatch.setenv("UPLOAD_MAX_MB", "1")

    with pytest.raises(HTTPException) as exc_info:
        await api.upload_document(_upload("large.txt", b"x" * (1024 * 1024 + 1)))

    assert exc_info.value.status_code == 413
    assert list(tmp_path.iterdir()) == []


@pytest.mark.asyncio
async def test_upload_returns_422_when_loader_produces_no_chunks(monkeypatch, tmp_path):
    monkeypatch.setattr(api, "upload_dir", lambda: tmp_path)
    monkeypatch.setattr(
        api,
        "save_document_to_pgvector",
        lambda *args, **kwargs: {"files": [], "total_parents": 0, "total_children": 0},
    )

    with pytest.raises(HTTPException) as exc_info:
        await api.upload_document(_upload("empty.txt", b""))

    assert exc_info.value.status_code == 422
    assert list(tmp_path.iterdir()) == []


@pytest.mark.asyncio
async def test_upload_does_not_leak_index_exception(monkeypatch, tmp_path):
    monkeypatch.setattr(api, "upload_dir", lambda: tmp_path)

    def fail(*args, **kwargs):
        raise RuntimeError("postgres password=secret host=/private/path")

    monkeypatch.setattr(api, "save_document_to_pgvector", fail)

    with pytest.raises(HTTPException) as exc_info:
        await api.upload_document(_upload("notes.md", b"hello"))

    assert exc_info.value.status_code == 500
    assert exc_info.value.detail == "Document indexing failed"
    assert "secret" not in exc_info.value.detail
    assert list(tmp_path.iterdir()) == []


def test_rag_serialization_does_not_expose_source_paths_or_path_metadata():
    doc = SimpleNamespace(
        id=1,
        content="hello",
        source_name="report.txt",
        source_path="/private/temp/uuid.txt",
        chunk_level="parent",
        chunk_index=0,
        parent_id=None,
        start_index=0,
        meta_data={"source": "/private/temp/uuid.txt", "page": 1},
    )

    result = _serialize_rag_document(doc)

    assert "source_path" not in result
    assert "source" not in result["metadata"]
    assert result["metadata"]["page"] == 1
