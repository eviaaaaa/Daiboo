"""
Qwen 模型初始化模块
提供统一的模型配置和初始化接口

注意：langchain-community 0.4 的 ChatTongyi 内置的多模态模型白名单
只包含旧版 qwen-vl-* / qwen-audio-* 系列。
对于 qwen3.5-plus 等新模型，DashScope 要求必须走
MultiModalConversation.call() (multimodal-generation 端点)，
但 ChatTongyi 不认识它们，会错误地路由到 Generation.call()。
因此我们在初始化后手动修正 client。
"""
import dashscope
from langchain_community.chat_models import tongyi

# 需要强制走 MultiModalConversation 端点的模型（DashScope 要求）
# ChatTongyi 只在 model_name 包含 "vl" 或在其内部白名单中时才自动切换，
# 所以这里列出那些不含 "vl" 但仍需要多模态端点的新模型。
FORCE_MULTIMODAL_MODELS = [
    "qwen3.5-plus",
]


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

    Args:
        model_name: 模型名称，默认 "qwen3.5-plus"
        temperature: 温度参数，默认 0.0
        request_timeout: 请求超时时间（秒），默认 3000
        **extra_kwargs: 传递给 ChatTongyi 的额外参数

    Returns:
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
    
    Args:
        content: str 或 list[dict] 格式的消息内容
    
    Returns:
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
