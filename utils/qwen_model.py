"""
模型初始化模块。

默认沿用 DashScope / ChatTongyi；当环境中配置了 OpenAI 兼容接口
（OPENAI_API_KEY，可选 OPENAI_BASE_URL / OPENAI_MODEL）时，主聊天模型可
直接复用 Hermes 等本地网关的 token 与 endpoint，降低本地启动门槛。

注意：langchain-community 0.4 的 ChatTongyi 内置的多模态模型白名单
只包含旧版 qwen-vl-* / qwen-audio-* 系列。
对于 qwen3.5-plus 等新模型，DashScope 要求必须走
MultiModalConversation.call() (multimodal-generation 端点)，
但 ChatTongyi 不认识它们，会错误地路由到 Generation.call()。
因此我们在初始化后手动修正 client。
"""
import os

import dashscope
from langchain_community.chat_models import tongyi

# 需要强制走 MultiModalConversation 端点的模型（DashScope 要求）
# ChatTongyi 只在 model_name 包含 "vl" 或在其内部白名单中时才自动切换，
# 所以这里列出那些不含 "vl" 但仍需要多模态端点的新模型。
FORCE_MULTIMODAL_MODELS = [
    "qwen3.5-plus",
]


def _env_value(name: str) -> str:
    return (os.getenv(name) or "").strip()


def create_openai_compatible_model(
    model_name: str | None = None,
    temperature: float = 0.0,
    request_timeout: int = 3000,
    **extra_kwargs,
):
    """Create a ChatOpenAI model from OPENAI_* environment variables.

    The import is intentionally lazy so lightweight tests that only exercise
    non-LLM helpers do not require ``langchain-openai`` to be installed.
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

    configured_model = model_name or _env_value("OPENAI_MODEL") or "gpt-4o-mini"
    base_url = _env_value("OPENAI_BASE_URL") or None
    return ChatOpenAI(
        model=configured_model,
        api_key=api_key,
        base_url=base_url,
        temperature=temperature,
        timeout=request_timeout,
        **extra_kwargs,
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
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict):
                parts.append(item.get("text", ""))
            elif isinstance(item, str):
                parts.append(item)
        return "".join(parts)
    return str(content)
