import importlib.util
from pathlib import Path


def _load_embeddings_module():
    module_path = Path(__file__).resolve().parents[1] / "utils" / "qwen_embeddings.py"
    spec = importlib.util.spec_from_file_location("test_qwen_embeddings_local_module", module_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_local_embedding_mode_returns_stable_1536_dimensional_vectors(monkeypatch):
    monkeypatch.setenv("NAXUSSURF_LOCAL_EMBEDDINGS", "1")
    module = _load_embeddings_module()
    embeddings = module.QwenEmbeddings()

    first = embeddings.embed_query("browser agent MCP tools")
    same = embeddings.embed_query("browser agent MCP tools")
    different = embeddings.embed_query("totally different content")

    assert len(first) == 1536
    assert first == same
    assert first != different


def test_local_embedding_mode_supports_document_batches(monkeypatch):
    monkeypatch.setenv("NAXUSSURF_LOCAL_EMBEDDINGS", "1")
    module = _load_embeddings_module()

    vectors = module.QwenEmbeddings().embed_documents(["alpha", "beta"])

    assert len(vectors) == 2
    assert all(len(vector) == 1536 for vector in vectors)
    assert vectors[0] != vectors[1]
