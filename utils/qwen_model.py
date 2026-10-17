"""
模型初始化模块。

默认沿用 DashScope / ChatTongyi；当环境中配置了 OpenAI 兼容接口
（OPENAI_API_KEY / OPENAI_MODEL，可选 OPENAI_BASE_URL）时，主聊天模型可
直接复用 Hermes 等本地网关的 token 与 endpoint，降低本地启动门槛。

注意：langchain-community 0.4 的 ChatTongyi 内置的多模态模型白名单
只包含旧版 qwen-vl-* / qwen-audio-* 系列。
对于 qwen3.5-plus 等新模型，DashScope 要求必须走
MultiModalConversation.call() (multimodal-generation 端点)，
但 ChatTongyi 不认识它们，会错误地路由到 Generation.call()。
因此我们在初始化后手动修正 client。
"""
import importlib
import math
import os

# 需要强制走 MultiModalConversation 端点的模型（DashScope 要求）
# ChatTongyi 只在 model_name 包含 "vl" 或在其内部白名单中时才自动切换，
# 所以这里列出那些不含 "vl" 但仍需要多模态端点的新模型。
FORCE_MULTIMODAL_MODELS = [
    "qwen3.5-plus",
]


def _env_value(name: str) -> str:
    return (os.getenv(name) or "").strip()


def is_openai_compatible_configured() -> bool:
    return bool(_env_value("OPENAI_API_KEY"))


def _env_bool(name: str, default: bool = False) -> bool:
    value = _env_value(name).lower()
    if not value:
        return default
    if value not in {"true", "false", "1", "0"}:
        raise ValueError(f"{name} must be true/false or 1/0")
    return value in {"true", "1"}


def _openai_responses_mode(api_mode: str | None, kwargs: dict) -> bool:
    """Make routing explicit rather than relying on model-name heuristics."""
    explicit = kwargs.pop("use_responses_api", None)
    if explicit is not None and not isinstance(explicit, bool):
        raise ValueError("use_responses_api must be a boolean")
    mode = (api_mode or "").strip().lower()
    if not mode and explicit is not None:
        return explicit
    if not mode:
        mode = _env_value("OPENAI_API_MODE").lower()
        legacy = _env_value("OPENAI_USE_RESPONSES_API")
        if mode and legacy and (mode == "responses") != _env_bool("OPENAI_USE_RESPONSES_API"):
            raise ValueError("OPENAI_API_MODE and OPENAI_USE_RESPONSES_API conflict")
        if not mode:
            return _env_bool("OPENAI_USE_RESPONSES_API")
    if mode not in {"chat_completions", "responses"}:
        raise ValueError("OPENAI_API_MODE must be chat_completions or responses")
    responses = mode == "responses"
    if explicit is not None and responses != explicit:
        raise ValueError("api_mode and use_responses_api conflict")
    return responses


def create_openai_compatible_model(
    model_name: str | None = None,
    temperature: float | None = None,
    request_timeout: int = 3000,
    *,
    api_mode: str | None = None,
    max_output_tokens: int | None = None,
    **extra_kwargs,
):
    """Create a ChatOpenAI model from OPENAI_* environment variables.

    OPENAI_MODEL is required unless model_name is explicit; provider/model
    capabilities are not inferred. OPENAI_API_MODE selects chat_completions
    (default) or responses; OPENAI_USE_RESPONSES_API is a legacy boolean alias.
    OPENAI_STREAMING enables native SDK SSE for either protocol.

    Optional OPENAI_REASONING_EFFORT, OPENAI_REASONING_SUMMARY (Responses only),
    OPENAI_VERBOSITY, OPENAI_SERVICE_TIER, OPENAI_MAX_OUTPUT_TOKENS and
    OPENAI_TEMPERATURE map to official ChatOpenAI fields. Unset temperature is
    omitted: not all reasoning models accept sampling parameters. Explicit
    constructor kwargs take precedence over environment defaults.

    Responses uses the official responses/v1 content blocks and requests
    encrypted reasoning for replay; no flattening or synthetic wire protocol.
    History stays local by default (use_previous_response_id=False). Provider
    storage remains its own default unless callers explicitly set store.
    The integrations remain lazily imported for the DashScope path.

    langchain-openai >=1.7.2 also preserves encrypted_content arriving only on
    SSE output_item.done; the local HTTP contract tests guard that replay path.
    """
    api_key = _env_value("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is required for OpenAI-compatible model mode")

    try:
        from langchain_openai import ChatOpenAI
    except ImportError as exc:  # pragma: no cover - depends on optional package install state
        raise RuntimeError(
            "langchain-openai is required when OPENAI_API_KEY is configured. "
            "Install it or unset OPENAI_API_KEY to use DashScope/ChatTongyi."
        ) from exc

    configured_model = (model_name or "").strip() or _env_value("OPENAI_MODEL")
    if not configured_model:
        raise ValueError("OPENAI_MODEL or an explicit model_name is required; no model is guessed")
    responses = _openai_responses_mode(api_mode, extra_kwargs)
    options = dict(extra_kwargs)
    options["use_responses_api"] = responses
    if "streaming" not in options:
        options["streaming"] = _env_bool("OPENAI_STREAMING")

    for field, env_name in (
        ("verbosity", "OPENAI_VERBOSITY"),
        ("service_tier", "OPENAI_SERVICE_TIER"),
    ):
        if field not in options and (value := _env_value(env_name)):
            options[field] = value

    effort = options.pop("reasoning_effort", _env_value("OPENAI_REASONING_EFFORT") or None)
    summary = _env_value("OPENAI_REASONING_SUMMARY") or None
    if responses:
        if "reasoning" not in options:
            reasoning = {}
            if effort is not None:
                reasoning["effort"] = effort
            if summary is not None:
                reasoning["summary"] = summary
            if reasoning:
                options["reasoning"] = reasoning
        elif effort is not None and "reasoning_effort" in extra_kwargs:
            raise ValueError("Pass reasoning or reasoning_effort, not both")
        options.setdefault("output_version", "responses/v1")
        options.setdefault("use_previous_response_id", False)
        include = list(options.get("include") or [])
        if "reasoning.encrypted_content" not in include:
            include.append("reasoning.encrypted_content")
        options["include"] = include
    else:
        if summary or options.get("reasoning") is not None:
            raise ValueError("Reasoning summary/reasoning requires Responses API mode")
        if options.get("output_version") == "responses/v1":
            raise ValueError("output_version=responses/v1 requires Responses API mode")
        if effort is not None:
            options["reasoning_effort"] = effort

    if "max_completion_tokens" not in options and "max_tokens" not in options:
        cap = max_output_tokens
        if cap is None and (value := _env_value("OPENAI_MAX_OUTPUT_TOKENS")):
            try:
                cap = int(value)
            except ValueError as exc:
                raise ValueError("OPENAI_MAX_OUTPUT_TOKENS must be a positive integer") from exc
        if cap is not None:
            if isinstance(cap, bool) or not isinstance(cap, int) or cap <= 0:
                raise ValueError("OPENAI_MAX_OUTPUT_TOKENS must be a positive integer")
            # ChatOpenAI renames this field to max_output_tokens for Responses.
            options["max_completion_tokens"] = cap

    if temperature is None and (value := _env_value("OPENAI_TEMPERATURE")):
        try:
            temperature = float(value)
        except ValueError as exc:
            raise ValueError("OPENAI_TEMPERATURE must be a finite number") from exc
        if not math.isfinite(temperature):
            raise ValueError("OPENAI_TEMPERATURE must be a finite number")
    base_url = _env_value("OPENAI_BASE_URL") or None
    return ChatOpenAI(
        model=configured_model,
        api_key=api_key,
        base_url=base_url,
        temperature=temperature,
        timeout=request_timeout,
        **options,
    )


def create_qwen_model(
    model_name: str = "qwen3.5-plus",
    temperature: float = 0.0,
    request_timeout: int = 3000,
    **extra_kwargs
):
    """
    创建 Qwen 模型实例

    针对 DashScope 要求走 MultiModalConversation 端点但 ChatTongyi
    未识别的新模型，会在初始化后手动修正 client。

    参数：
        model_name: 模型名称，默认 "qwen3.5-plus"
        temperature: 温度参数，默认 0.0
        request_timeout: 请求超时时间（秒），默认 3000
        **extra_kwargs: 传递给 ChatTongyi 的额外参数

    返回：
        配置好的 ChatTongyi 模型实例
    """
    dashscope = importlib.import_module("dashscope")
    tongyi = importlib.import_module("langchain_community.chat_models.tongyi")

    model = tongyi.ChatTongyi(
        model_name=model_name,
        temperature=temperature,
        request_timeout=request_timeout,
        **extra_kwargs,
    )

    # 修正端点：如果模型需要多模态端点但 ChatTongyi 没有自动识别，
    # 则将 client 从 dashscope.Generation 替换为 dashscope.MultiModalConversation
    needs_multimodal = any(m in model_name for m in FORCE_MULTIMODAL_MODELS)
    if needs_multimodal and model.client is not dashscope.MultiModalConversation:
        model.client = dashscope.MultiModalConversation

    return model


def normalize_content(content):
    """
    标准化消息 content：MultiModalConversation 端点返回的 content
    是 list[dict] 格式 (如 [{"text": "..."}])，
    而下游代码（数据库存储、JSON 解析等）期望 str。
    
    参数：
        content: str 或 list[dict] 格式的消息内容
    
    返回：
        纯文本字符串
    """
    # Display-only projection. Never mutate AIMessage replay blocks or IDs.
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict):
                kind = item.get("type")
                if kind in (None, "text", "input_text", "output_text"):
                    text = item.get("text")
                elif kind == "refusal":
                    text = item.get("refusal")
                else:
                    continue
                if isinstance(text, str):
                    parts.append(text)
            elif isinstance(item, str):
                parts.append(item)
        return "".join(parts)
    return str(content)
