def test_rag_debug_search_returns_cached_payload_without_database(monkeypatch):
    from rag import document_rag_pgvector as rag

    cached = {
        "query": "缓存测试",
        "top_k": 3,
        "use_rerank": False,
        "legacy_fallback_used": False,
        "chunk_config": {},
        "strategies": {"large_chunks": [], "small_chunks": [], "hierarchical": []},
    }
    monkeypatch.setattr(rag, "versioned_cache_key", lambda *parts: "rag-key")
    monkeypatch.setattr(rag, "get_json", lambda key: cached)
    monkeypatch.setattr(rag, "ensure_rag_document_schema", lambda: (_ for _ in ()).throw(AssertionError("DB touched")))

    assert rag.debug_query_document_from_pgvector("缓存测试", 3, False) == cached


def test_production_rag_search_returns_cached_documents_without_database(monkeypatch):
    from rag import document_rag_pgvector as rag

    cached = [
        {
            "content": "缓存命中的父块",
            "source_name": "guide.md",
            "chunk_level": "parent",
            "chunk_index": 2,
            "parent_id": None,
            "start_index": 128,
            "metadata": {"section": "cache", "source_path": "/private/path"},
        }
    ]
    monkeypatch.setattr(rag, "versioned_cache_key", lambda *parts: "rag-search-key")
    monkeypatch.setattr(rag, "get_json", lambda key: cached)
    monkeypatch.setattr(
        rag,
        "ensure_rag_document_schema",
        lambda: (_ for _ in ()).throw(AssertionError("DB touched")),
    )

    documents = rag.query_document_from_pgvector("缓存测试", 3, False)

    assert len(documents) == 1
    assert documents[0].content == "缓存命中的父块"
    assert documents[0].embedding is None
    assert documents[0].source_path is None
    assert "source_path" not in documents[0].meta_data


def test_rag_summary_returns_cached_payload_without_database(monkeypatch):
    from rag import document_rag_pgvector as rag

    cached = {
        "total_parent_chunks": 2,
        "total_child_chunks": 6,
        "total_legacy_rows": 0,
        "sources": [],
    }
    monkeypatch.setattr(rag, "versioned_cache_key", lambda *parts: "summary-key")
    monkeypatch.setattr(rag, "get_json", lambda key: cached)
    monkeypatch.setattr(rag, "ensure_rag_document_schema", lambda: (_ for _ in ()).throw(AssertionError("DB touched")))

    assert rag.get_rag_corpus_summary() == cached


def test_query_embeddings_use_cached_vector(monkeypatch):
    from utils import qwen_embeddings as embeddings_module

    monkeypatch.setenv("DAIBOO_LOCAL_EMBEDDINGS", "1")
    cached = [0.25] * 1536
    monkeypatch.setattr(embeddings_module, "cache_key", lambda *parts: "embedding-key")
    monkeypatch.setattr(embeddings_module, "get_json", lambda key: cached)

    embeddings = embeddings_module.QwenEmbeddings()

    assert embeddings.embed_query("same query") == cached


def test_rag_writes_bump_cache_namespace():
    from pathlib import Path

    source = (Path(__file__).resolve().parents[1] / "rag" / "document_rag_pgvector.py").read_text(encoding="utf-8")

    assert "bump_namespace(\"rag\")" in source
