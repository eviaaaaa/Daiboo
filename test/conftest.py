from __future__ import annotations

import pytest

_PROVIDER_CONFIG_TESTS = (
    "test_qwen_embeddings_config.py",
    "test_utils_lazy_exports.py",
)


@pytest.fixture(autouse=True)
def default_to_local_embeddings(monkeypatch, request):
    """Keep integration-style tests deterministic and offline by default.

    Provider configuration tests opt out so they can verify OpenAI-compatible
    and DashScope selection without the local-embedding override.
    """
    nodeid = request.node.nodeid
    if any(test_file in nodeid for test_file in _PROVIDER_CONFIG_TESTS):
        monkeypatch.delenv("NAXUSSURF_LOCAL_EMBEDDINGS", raising=False)
        return
    monkeypatch.setenv("NAXUSSURF_LOCAL_EMBEDDINGS", "1")

    # Some provider-selection tests import the singleton with fake provider
    # classes. If later integration tests reuse that already-imported module,
    # force it back to the deterministic local backend for this test case.
    try:
        from utils.qwen_embeddings import qwen_embeddings
    except Exception:
        return
    monkeypatch.setattr(qwen_embeddings, "_use_local_embeddings", True, raising=False)
    monkeypatch.setattr(qwen_embeddings, "_openai_embeddings", None, raising=False)
