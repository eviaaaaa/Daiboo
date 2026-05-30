import importlib.util
import sys
import types
from pathlib import Path


def _load_embeddings_module():
    module_path = Path(__file__).resolve().parents[1] / "utils" / "qwen_embeddings.py"
    spec = importlib.util.spec_from_file_location("test_qwen_embeddings_module", module_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_embedding_uses_openai_compatible_provider_when_configured(monkeypatch):
    calls = []

    class FakeEmbeddings:
        def __init__(self, **kwargs):
            self.kwargs = kwargs
            calls.append(("init", kwargs))

        def embed_documents(self, texts):
            calls.append(("embed_documents", texts))
            return [[float(i)] * 1536 for i, _ in enumerate(texts, 1)]

        def embed_query(self, text):
            calls.append(("embed_query", text))
            return [0.5] * 1536

    fake_langchain_openai = types.SimpleNamespace(OpenAIEmbeddings=FakeEmbeddings)
    monkeypatch.setitem(sys.modules, "langchain_openai", fake_langchain_openai)
    monkeypatch.setenv("OPENAI_API_KEY", " test-key ")
    monkeypatch.setenv("OPENAI_BASE_URL", " https://example.test/v1 ")
    monkeypatch.setenv("OPENAI_EMBEDDING_MODEL", " text-embedding-3-small ")

    module = _load_embeddings_module()
    embeddings = module.QwenEmbeddings()

    assert embeddings.embed_query("hello") == [0.5] * 1536
    assert embeddings.embed_documents(["a", "b"])[1] == [2.0] * 1536
    assert calls[0][0] == "init"
    assert calls[0][1]["api_key"] == "test-key"
    assert calls[0][1]["base_url"] == "https://example.test/v1"
    assert calls[0][1]["model"] == "text-embedding-3-small"


def test_embedding_falls_back_to_dashscope_without_openai_key(monkeypatch):
    calls = []

    class FakeTextEmbedding:
        @staticmethod
        def call(**kwargs):
            calls.append(kwargs)
            return types.SimpleNamespace(
                status_code=200,
                output={"embeddings": [{"embedding": [1.0] * 1536}]},
            )

    fake_dashscope = types.SimpleNamespace(TextEmbedding=FakeTextEmbedding)
    monkeypatch.setitem(sys.modules, "dashscope", fake_dashscope)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    module = _load_embeddings_module()

    assert module.QwenEmbeddings().embed_query("hello") == [1.0] * 1536
    assert calls[0]["model"] == "text-embedding-v1"
    assert calls[0]["text_type"] == "query"
