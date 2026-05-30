import importlib
import sys
import types


def test_qwen_embeddings_export_is_created_after_env_is_available(monkeypatch):
    for name in [
        "utils",
        "utils.qwen_embeddings",
    ]:
        sys.modules.pop(name, None)

    class FakeOpenAIEmbeddings:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    monkeypatch.setitem(
        sys.modules,
        "langchain_openai",
        types.SimpleNamespace(OpenAIEmbeddings=FakeOpenAIEmbeddings),
    )
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    import utils  # noqa: F401 - package import should not construct embeddings yet

    monkeypatch.setenv("OPENAI_API_KEY", "late-key")
    from utils import qwen_embeddings

    assert qwen_embeddings._openai_embeddings is not None
    assert qwen_embeddings._openai_embeddings.kwargs["api_key"] == "late-key"
