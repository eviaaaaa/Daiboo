"""diff middleware：给所有"会改页面状态"的 MCP 浏览器工具自动附 DOM diff + 瞬时文本。

设计：参考 GenericAgent/simphtml.py 的 execute_js_rich，把"动作 + 自动验证"压缩到一次工具调用。
LLM 执行 browser_click 或 browser_type 后，工具结果末尾会自动追加：
- [diff] DOM 变化量: N
- 最显著变化片段（最长那个 outerHTML，截到 2000 字符）
- [transients] 动作期间出现的瞬时文本（toast / 错误提示 / loading）

省下 LLM 通常要"做动作 → 再 snapshot 验证"的下一轮。

源算法来自 https://github.com/lsdefine/GenericAgent (MIT)。
详见 docx/genericagent_investigation.md 与 docx/genericagent_improvement_plan.md。
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable

from langchain.agents.middleware import wrap_tool_call
from langchain_core.messages import ToolMessage

from tools._simphtml import (
    find_changed_elements,
    find_evaluate_tool,
    observe_simplified,
    start_transient_monitor,
    stop_transient_monitor,
)

logger = logging.getLogger(__name__)


# ── 配置：哪些工具调用前后要做 diff ───────────────────────────────────
# 命名以 @playwright/mcp 当前提供的工具为准。改 MCP 版本时同步检查。
STATE_CHANGING_TOOLS: set[str] = {
    "browser_click",
    "browser_hover",
    "browser_drag",
    "browser_type",
    "browser_fill_form",
    "browser_select_option",
    "browser_press_key",
    "browser_navigate",
    "browser_navigate_back",
    "browser_handle_dialog",
    "browser_file_upload",
    "browser_evaluate",
    "browser_run_code",
}

# 单次 before/after observation 的超时上限（秒）。MCP 会话繁忙时不要把 agent 拖死。
_OBSERVE_TIMEOUT = 2.0
# 瞬时监视器启停超时
_MONITOR_TIMEOUT = 1.5


def make_diff_middleware(mcp_tools: list[Any]) -> Callable:
    """工厂：给定 MCP 工具列表，返回挂在 agent middleware 链上的 wrapped 函数。

    用工厂模式而不是 module-level global，是因为 mcp_tools 的生命周期由
    `utils/mcp_client.create_persistent_mcp_session` 管理，每次 session 启动都是
    一份新的工具列表。
    """
    eval_tool_holder: dict[str, Any] = {"eval_tool": None}

    def _resolve_eval_tool() -> Any:
        if eval_tool_holder["eval_tool"] is None:
            eval_tool_holder["eval_tool"] = find_evaluate_tool(mcp_tools)
        return eval_tool_holder["eval_tool"]

    @wrap_tool_call
    async def diff_middleware(request, handler):
        tool_name = getattr(request.tool, "name", "")
        if tool_name not in STATE_CHANGING_TOOLS:
            return await handler(request)

        eval_tool = _resolve_eval_tool()
        if eval_tool is None:
            # browser_evaluate 不可用时跳过 diff，不影响原工具调用
            return await handler(request)

        # 1. 拍 before snapshot（best-effort）
        before_html = await observe_simplified(
            eval_tool, text_only=False, timeout_seconds=_OBSERVE_TIMEOUT
        )

        # 2. 启动瞬时文本监视器
        await start_transient_monitor(eval_tool, timeout_seconds=_MONITOR_TIMEOUT)

        # 3. 跑原工具
        response = await handler(request)

        # 4. 拍 after snapshot
        after_html = await observe_simplified(
            eval_tool, text_only=False, timeout_seconds=_OBSERVE_TIMEOUT
        )

        # 5. 收瞬时文本
        transients = await stop_transient_monitor(
            eval_tool, timeout_seconds=_MONITOR_TIMEOUT
        )

        # 6. 计算 diff，追加到响应
        return _augment_response_with_diff(
            response,
            tool_name=tool_name,
            before_html=before_html,
            after_html=after_html,
            transients=transients,
        )

    return diff_middleware


def _augment_response_with_diff(
    response: Any,
    *,
    tool_name: str,
    before_html: str | None,
    after_html: str | None,
    transients: list[str],
) -> Any:
    """把 diff 摘要追加到 ToolMessage.content。

    若 response 不是 ToolMessage（理论上不应发生）原样返回，不阻断主流程。
    若两次 snapshot 都失败，同样原样返回。
    """
    extras: list[str] = []

    if before_html and after_html:
        try:
            diff_data = find_changed_elements(before_html, after_html)
        except Exception as exc:
            logger.debug("diff_middleware: find_changed_elements 异常: %s", exc)
            diff_data = {"changed": 0}

        changed = diff_data.get("changed", 0)
        if changed > 0:
            extras.append(f"[diff] DOM 变化量: {changed}")
            top = diff_data.get("top_change")
            if top:
                extras.append(f"[diff] 最显著变化:\n{top}")
        else:
            extras.append("[diff] 页面无明显变化")
    elif before_html is None and after_html is None:
        # 两次都失败，可能是 CSP 严格站点，不打扰
        pass
    else:
        extras.append("[diff] 部分 snapshot 失败，无法计算变化")

    if transients:
        # 同字符串很多重复，去重
        unique = list(dict.fromkeys(transients))
        # 长度截断防止刷屏
        if len(unique) > 10:
            unique = unique[:10] + [f"... (still {len(transients) - 10} more)"]
        extras.append(f"[transients] {unique}")

    if not extras:
        return response

    extra_text = "\n\n" + "\n".join(extras)

    # 安全地追加到 content。content 可能是 str 或 list[dict]。
    if isinstance(response, ToolMessage):
        return _clone_tool_message_with_extra(response, extra_text)
    # 退路：response 不是 ToolMessage，尝试直接修改 content
    try:
        if isinstance(getattr(response, "content", None), str):
            response.content = response.content + extra_text
    except Exception:
        pass
    return response


def _clone_tool_message_with_extra(msg: ToolMessage, extra: str) -> ToolMessage:
    """在 ToolMessage 上追加文本并返回新对象（不修改原 msg）。"""
    new_content: Any
    if isinstance(msg.content, str):
        new_content = msg.content + extra
    elif isinstance(msg.content, list):
        # ToolMessage 多模态格式：list[dict]
        new_content = list(msg.content) + [{"type": "text", "text": extra}]
    else:
        new_content = str(msg.content) + extra

    return ToolMessage(
        content=new_content,
        tool_call_id=msg.tool_call_id,
        name=msg.name,
        artifact=getattr(msg, "artifact", None),
        status=getattr(msg, "status", "success"),
        additional_kwargs=getattr(msg, "additional_kwargs", {}),
        response_metadata=getattr(msg, "response_metadata", {}),
    )
