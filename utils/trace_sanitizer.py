"""
trace_sanitizer.py
==================
多模态图文数据智能裁剪截断策略

在 AgentTrace 落库前，对 full_trace 中每条消息的 content 进行清洗：
  1. Base64 图片检测 & 替换 —— 防止大体积二进制数据污染 JSON 字段
  2. 超长 Tool 返回内容截断 —— 防止网页 HTML/截图文本撑爆磁盘
  3. 嵌套 list[dict] 多模态结构展平 —— 保证统一的字符串输出

核心原则：只做"落库前清洗"，不影响 Agent 运行时的真实消息内容。
"""

import re
import json
from typing import Any

# ── 阈值常量（可按需调整）──────────────────────────────────────────────
# Tool 返回内容超过此长度（字符）时触发截断，保留头尾各一段
TOOL_CONTENT_MAX_CHARS: int = 3000
# 截断时保留的头部字符数
TOOL_CONTENT_HEAD_CHARS: int = 1500
# 截断时保留的尾部字符数
TOOL_CONTENT_TAIL_CHARS: int = 500
# AI / Human 消息内容超过此长度时也截断（通常更宽松）
TEXT_CONTENT_MAX_CHARS: int = 8000

# ── Base64 检测正则 ────────────────────────────────────────────────────
# 匹配 data:image/xxx;base64, 或者纯 Base64 块（>=200 个 base64 字符）
_BASE64_INLINE_RE = re.compile(
    r'data:image/[^;]+;base64,[A-Za-z0-9+/=]+', re.IGNORECASE
)
_BASE64_RAW_RE = re.compile(
    r'(?<![A-Za-z0-9+/])[A-Za-z0-9+/]{200,}={0,2}(?![A-Za-z0-9+/])'
)


# ── 公开入口 ───────────────────────────────────────────────────────────

def sanitize_trace(serialized_trace: list[dict]) -> list[dict]:
    """
    对完整链路列表进行裁剪，返回新的 list（不修改原始对象）。

    Args:
        serialized_trace: screen_logger 中已初步序列化的消息列表，
                          每条格式为 {"role": str, "content": str|list, ...}

    Returns:
        清洗后的消息列表，可直接作为 AgentTrace.full_trace 入库。
    """
    cleaned = []
    for msg in serialized_trace:
        cleaned.append(_sanitize_message(msg))
    return cleaned


# ── 内部实现 ───────────────────────────────────────────────────────────

def _sanitize_message(msg: dict) -> dict:
    """处理单条消息，返回副本（不修改原始 dict）。"""
    msg = dict(msg)  # 浅拷贝，避免修改原始链路
    role = msg.get("role", "")
    content = msg.get("content", "")

    # Step 1: 展平多模态 list[dict] 结构
    content = _flatten_multimodal(content)

    # Step 2: 根据角色选择截断规则
    if role == "tool":
        content = _sanitize_tool_content(content)
    else:
        content = _sanitize_text_content(content)

    msg["content"] = content

    # Step 3: 清洗 tool_calls 参数中的 base64（极少见但存在）
    if "tool_calls" in msg and isinstance(msg["tool_calls"], list):
        msg["tool_calls"] = _sanitize_tool_calls(msg["tool_calls"])

    return msg


def _flatten_multimodal(content: Any) -> str:
    """
    将多模态 list[dict] 内容展平为纯文本。
    支持格式：
      - str → 直接返回
      - [{"type": "text", "text": "..."}, {"type": "image_url", ...}]
      - [{"text": "..."}]（DashScope 格式）
    """
    if isinstance(content, str):
        return content

    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict):
                item_type = item.get("type", "")
                if item_type == "image_url":
                    # 图片块：只保留占位符，不保存 URL/base64
                    url = item.get("image_url", {})
                    if isinstance(url, dict):
                        url = url.get("url", "")
                    if _is_base64(str(url)):
                        parts.append("[IMAGE: base64 data removed]")
                    else:
                        parts.append(f"[IMAGE: {str(url)[:80]}]")
                elif item_type in ("text", ""):
                    # 优先取 text，兼容 DashScope {text: ...} 格式
                    parts.append(item.get("text") or item.get("content") or "")
                else:
                    # 其他类型（audio、video 等）记录占位符
                    parts.append(f"[{item_type.upper()} DATA REMOVED]")
            elif isinstance(item, str):
                parts.append(item)
        return "".join(parts)

    return str(content)


def _sanitize_tool_content(text: str) -> str:
    """
    针对 ToolMessage（工具返回）的截断策略：
    1. 移除内嵌 base64 图片
    2. 超长时保留头尾，中间替换为摘要标记
    """
    # 先移除 base64
    text = _strip_base64(text)

    if len(text) <= TOOL_CONTENT_MAX_CHARS:
        return text

    # 头尾截断，中间插入提示
    head = text[:TOOL_CONTENT_HEAD_CHARS]
    tail = text[-TOOL_CONTENT_TAIL_CHARS:] if TOOL_CONTENT_TAIL_CHARS > 0 else ""
    omitted = len(text) - TOOL_CONTENT_HEAD_CHARS - TOOL_CONTENT_TAIL_CHARS
    mid = f"\n... [{omitted} chars truncated] ...\n"

    return head + mid + tail


def _sanitize_text_content(text: str) -> str:
    """
    针对 AI / Human 消息的截断策略（更宽松）：
    1. 移除内嵌 base64
    2. 整体超长时尾部截断
    """
    text = _strip_base64(text)

    if len(text) > TEXT_CONTENT_MAX_CHARS:
        omitted = len(text) - TEXT_CONTENT_MAX_CHARS
        text = text[:TEXT_CONTENT_MAX_CHARS] + f"\n... [{omitted} chars truncated]"

    return text


def _sanitize_tool_calls(tool_calls: list) -> list:
    """处理 AIMessage.tool_calls 列表中参数里可能含有的 base64。"""
    result = []
    for tc in tool_calls:
        tc = dict(tc)
        if "args" in tc and isinstance(tc["args"], dict):
            cleaned_args = {}
            for k, v in tc["args"].items():
                if isinstance(v, str) and _is_base64(v):
                    cleaned_args[k] = "[BASE64 DATA REMOVED]"
                elif isinstance(v, str) and len(v) > TOOL_CONTENT_MAX_CHARS:
                    cleaned_args[k] = v[:TOOL_CONTENT_HEAD_CHARS] + f"\n... [truncated]"
                else:
                    cleaned_args[k] = v
            tc["args"] = cleaned_args
        result.append(tc)
    return result


def _strip_base64(text: str) -> str:
    """从字符串中移除 base64 图片数据，替换为占位符。"""
    # 先替换 data:image/xxx;base64,...
    text = _BASE64_INLINE_RE.sub("[BASE64_IMAGE_REMOVED]", text)
    # 再替换裸 Base64 块（容易误判，因此阈值设高到 200 字符）
    text = _BASE64_RAW_RE.sub("[BASE64_BLOCK_REMOVED]", text)
    return text


def _is_base64(value: str) -> bool:
    """快速判断字符串是否是 base64 图片。"""
    if value.startswith("data:image"):
        return True
    if len(value) > 200 and _BASE64_RAW_RE.search(value):
        return True
    return False
