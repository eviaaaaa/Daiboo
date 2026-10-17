import importlib.util
import os
import sys
import types
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def clean_openai_environment(monkeypatch):
    for name in list(os.environ):
        if name.startswith("OPENAI_"):
            monkeypatch.delenv(name, raising=False)


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


def test_create_openai_compatible_model_ignores_blank_model_argument(monkeypatch) -> None:
    fake_langchain_openai = types.SimpleNamespace(ChatOpenAI=_FakeChatOpenAI)
    monkeypatch.setitem(sys.modules, "langchain_openai", fake_langchain_openai)
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("OPENAI_MODEL", "env-model")

    qwen_model = _load_qwen_model_module()
    model = qwen_model.create_openai_compatible_model(model_name="   ")

    assert model.kwargs["model"] == "env-model"


def test_create_openai_compatible_model_ignores_blank_env_model(monkeypatch) -> None:
    fake_langchain_openai = types.SimpleNamespace(ChatOpenAI=_FakeChatOpenAI)
    monkeypatch.setitem(sys.modules, "langchain_openai", fake_langchain_openai)
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("OPENAI_MODEL", "   ")

    qwen_model = _load_qwen_model_module()
    model = qwen_model.create_openai_compatible_model(model_name="fallback-model")

    assert model.kwargs["model"] == "fallback-model"


def test_create_openai_compatible_model_requires_api_key(monkeypatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    qwen_model = _load_qwen_model_module()

    with pytest.raises(RuntimeError, match="OPENAI_API_KEY is required"):
        qwen_model.create_openai_compatible_model()


@pytest.fixture
def configured_model(monkeypatch):
    monkeypatch.setitem(sys.modules, "langchain_openai", types.SimpleNamespace(ChatOpenAI=_FakeChatOpenAI))
    monkeypatch.setenv("OPENAI_API_KEY", "inert-test-key")
    monkeypatch.setenv("OPENAI_MODEL", "explicit-model")
    return _load_qwen_model_module()


def test_no_guessed_model_when_openai_model_missing(monkeypatch, configured_model):
    monkeypatch.delenv("OPENAI_MODEL")
    with pytest.raises(ValueError, match="OPENAI_MODEL"):
        configured_model.create_openai_compatible_model()


def test_default_chat_does_not_guess_temperature_or_protocol(configured_model):
    model = configured_model.create_openai_compatible_model()
    assert model.kwargs["use_responses_api"] is False
    assert model.kwargs.get("temperature") is None
    assert "reasoning" not in model.kwargs
    assert "include" not in model.kwargs


@pytest.mark.parametrize("value", ["yes", "nonsense", "2"])
def test_invalid_boolean_is_an_error(monkeypatch, configured_model, value):
    monkeypatch.setenv("OPENAI_STREAMING", value)
    with pytest.raises(ValueError, match="OPENAI_STREAMING"):
        configured_model.create_openai_compatible_model()


def test_conflicting_protocol_flags_fail(monkeypatch, configured_model):
    monkeypatch.setenv("OPENAI_API_MODE", "chat_completions")
    monkeypatch.setenv("OPENAI_USE_RESPONSES_API", "true")
    with pytest.raises(ValueError, match="conflict"):
        configured_model.create_openai_compatible_model()


def test_responses_configuration_uses_official_fields(monkeypatch, configured_model):
    monkeypatch.setenv("OPENAI_USE_RESPONSES_API", "true")
    monkeypatch.setenv("OPENAI_STREAMING", "1")
    monkeypatch.setenv("OPENAI_REASONING_EFFORT", "high")
    monkeypatch.setenv("OPENAI_REASONING_SUMMARY", "auto")
    monkeypatch.setenv("OPENAI_VERBOSITY", "low")
    monkeypatch.setenv("OPENAI_SERVICE_TIER", "default")
    monkeypatch.setenv("OPENAI_MAX_OUTPUT_TOKENS", "100")
    model = configured_model.create_openai_compatible_model()
    assert model.kwargs["use_responses_api"] is True
    assert model.kwargs["streaming"] is True
    assert model.kwargs["reasoning"] == {"effort": "high", "summary": "auto"}
    assert model.kwargs["output_version"] == "responses/v1"
    assert model.kwargs["include"] == ["reasoning.encrypted_content"]
    assert model.kwargs["verbosity"] == "low"
    assert model.kwargs["service_tier"] == "default"
    assert model.kwargs["max_completion_tokens"] == 100
    assert model.kwargs["use_previous_response_id"] is False


def test_reasoning_summary_requires_responses(monkeypatch, configured_model):
    monkeypatch.setenv("OPENAI_REASONING_SUMMARY", "auto")
    with pytest.raises(ValueError, match="Responses"):
        configured_model.create_openai_compatible_model()


@pytest.mark.parametrize("value", ["0", "-1", "1.5", "unlimited"])
def test_invalid_output_cap_fails_before_request(monkeypatch, configured_model, value):
    monkeypatch.setenv("OPENAI_MAX_OUTPUT_TOKENS", value)
    with pytest.raises(ValueError, match="OPENAI_MAX_OUTPUT_TOKENS"):
        configured_model.create_openai_compatible_model()


def test_explicit_kwargs_override_environment(monkeypatch, configured_model):
    monkeypatch.setenv("OPENAI_API_MODE", "responses")
    monkeypatch.setenv("OPENAI_STREAMING", "true")
    monkeypatch.setenv("OPENAI_REASONING_EFFORT", "low")
    monkeypatch.setenv("OPENAI_MAX_OUTPUT_TOKENS", "90")
    model = configured_model.create_openai_compatible_model(
        streaming=False, reasoning={"effort": "high", "summary": "detailed"},
        max_completion_tokens=23, temperature=0.5,
        include=["message.input_image.image_url"],
    )
    assert model.kwargs["streaming"] is False
    assert model.kwargs["reasoning"] == {"effort": "high", "summary": "detailed"}
    assert model.kwargs["max_completion_tokens"] == 23
    assert model.kwargs["temperature"] == 0.5
    assert model.kwargs["include"] == ["message.input_image.image_url", "reasoning.encrypted_content"]


def test_normalize_visible_content_never_flattens_replay_blocks(configured_model):
    import copy

    content = [
        {"type": "reasoning", "text": "private", "summary": [], "encrypted_content": "opaque"},
        {"type": "function_call", "name": "lookup", "arguments": "{}", "text": "not display"},
        {"type": "text", "text": "visible "},
        {"text": "Qwen"}, " string",
        {"type": "refusal", "refusal": " refused"},
        {"type": "text", "text": None},
    ]
    snapshot = copy.deepcopy(content)
    assert configured_model.normalize_content(content) == "visible Qwen string refused"
    assert content == snapshot
    assert configured_model.normalize_content(None) == ""


def test_qwen_endpoint_and_temperature_compatibility(monkeypatch):
    generation, multimodal = object(), object()
    dashscope = types.SimpleNamespace(Generation=generation, MultiModalConversation=multimodal)

    class FakeTongyi:
        def __init__(self, **kwargs):
            self.client = generation
            self.kwargs = kwargs

    monkeypatch.setitem(sys.modules, "dashscope", dashscope)
    monkeypatch.setitem(sys.modules, "langchain_community.chat_models.tongyi", types.SimpleNamespace(ChatTongyi=FakeTongyi))
    module = _load_qwen_model_module()
    model = module.create_qwen_model(model_name="qwen3.5-plus", temperature=0.0)
    assert model.client is multimodal
    assert model.kwargs["temperature"] == 0.0
