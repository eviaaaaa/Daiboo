"""
Qwen 模型初始化模块
提供统一的模型配置和初始化接口
"""
from langchain_community.chat_models import tongyi

# Qwen 模型的 profile 配置
QWEN_PROFILE = {
    # --- Input constraints ---
    "max_input_tokens": 262_144,    # 对应 [limit] context
    
    # 对应 attachment = false 和 modalities input = ["text"]
    "image_inputs": False,
    "image_url_inputs": False,
    "pdf_inputs": False,
    "audio_inputs": False,
    "video_inputs": False,
    
    # 通常如果不支持多模态输入，也不支持在 Tool Message 中包含这些媒体
    "image_tool_message": False,
    "pdf_tool_message": False,

    # --- Output constraints ---
    "max_output_tokens": 65_536,    # 对应 [limit] output
    
    "reasoning_output": False,      # 对应 reasoning = false
    
    # 对应 modalities output = ["text"]
    "image_outputs": False,
    "audio_outputs": False,
    "video_outputs": False,

    # --- Tool calling ---
    "tool_calling": True,           # 对应 tool_call = true
}


def create_qwen_model(
    model_name: str = "qwen3-max",
    temperature: float = 0.0,
    request_timeout: int = 3000,
    profile: dict = None
):
    """
    创建 Qwen 模型实例
    
    Args:
        model_name: 模型名称，默认 "qwen3-max"
        temperature: 温度参数，默认 0.0
        request_timeout: 请求超时时间（秒），默认 3000
        profile: 模型配置，默认使用 QWEN_PROFILE
    
    Returns:
        配置好的 ChatTongyi 模型实例
    """
    if profile is None:
        profile = QWEN_PROFILE
    
    model = tongyi.ChatTongyi(
        model_name=model_name,
        temperature=temperature,
        request_timeout=request_timeout,
        profile=profile,
    )
    
    return model
