import pytest
from fastapi import HTTPException

import api


def test_cors_is_disabled_by_default(monkeypatch):
    monkeypatch.delenv("CORS_ALLOW_ORIGINS", raising=False)

    assert api._cors_origins() == []


def test_cors_uses_explicit_origin_allowlist(monkeypatch):
    monkeypatch.setenv("CORS_ALLOW_ORIGINS", "https://one.example, https://two.example")

    assert api._cors_origins() == ["https://one.example", "https://two.example"]


@pytest.mark.asyncio
async def test_rag_search_hides_internal_exception(monkeypatch):
    def fail(*args, **kwargs):
        raise RuntimeError("postgresql://user:secret@localhost/private")

    monkeypatch.setattr(api, "debug_query_document_from_pgvector", fail)

    with pytest.raises(HTTPException) as exc_info:
        await api.debug_rag_search(api.RagSearchRequest(query="hello"))

    assert exc_info.value.status_code == 500
    assert exc_info.value.detail == "RAG search failed"
    assert "secret" not in exc_info.value.detail


@pytest.mark.asyncio
async def test_rag_summary_hides_internal_exception(monkeypatch):
    def fail():
        raise RuntimeError("/private/database/path")

    monkeypatch.setattr(api, "get_rag_corpus_summary", fail)

    with pytest.raises(HTTPException) as exc_info:
        await api.rag_corpus_summary()

    assert exc_info.value.status_code == 500
    assert exc_info.value.detail == "RAG summary unavailable"
