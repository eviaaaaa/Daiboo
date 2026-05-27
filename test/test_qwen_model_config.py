import importlib.util
import sys
import types
from pathlib import Path

import pytest


def _load_qwen_model_module():
    module_path = Path(__file__).resolve().parents[1] / "utils" / "qwen_model.py"
    spec = importlib.util.spec_from_file_location("test_qwen_model_module", module_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_importing_qwen_model_does_not_import_dashscope_integrations(monkeypatch) -> None:
    sys.modules.pop("test_qwen_model_module", None)
    sys.modules.pop("dashscope", None)
    sys.modules.pop("langchain_community.chat_models.tongyi", None)

    _load_qwen_model_module()

    assert "dashscope" not in sys.modules
    assert "langchain_community.chat_models.tongyi" not in sys.modules


class _FakeChatOpenAI:
    def __init__(self, **kwargs):
        self.kwargs = kwargs


def test_is_openai_compatible_configured_ignores_whitespace_api_key(monkeypatch) -> None:
    qwen_model = _load_qwen_model_module()

    monkeypatch.setenv("OPENAI_API_KEY", "   ")
    assert qwen_model.is_openai_compatible_configured() is False

    monkeypatch.setenv("OPENAI_API_KEY", " real-key ")
    assert qwen_model.is_openai_compatible_configured() is True


def test_create_openai_compatible_model_strips_blank_base_url(monkeypatch) -> None:
    fake_langchain_openai = types.SimpleNamespace(ChatOpenAI=_FakeChatOpenAI)
    monkeypatch.setitem(sys.modules, "langchain_openai", fake_langchain_openai)
    monkeypatch.setenv("OPENAI_API_KEY", " test-key ")
    monkeypatch.setenv("OPENAI_BASE_URL", "   ")
    monkeypatch.setenv("OPENAI_MODEL", " test-model ")

    qwen_model = _load_qwen_model_module()
    model = qwen_model.create_openai_compatible_model(temperature=0.2, request_timeout=12)

    assert model.kwargs["api_key"] == "test-key"
    assert model.kwargs["model"] == "test-model"
    assert model.kwargs["base_url"] is None
    assert model.kwargs["temperature"] == 0.2
    assert model.kwargs["timeout"] == 12


def test_create_openai_compatible_model_requires_api_key(monkeypatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    qwen_model = _load_qwen_model_module()

    with pytest.raises(RuntimeError, match="OPENAI_API_KEY is required"):
        qwen_model.create_openai_compatible_model()
