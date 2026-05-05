"""共享的浏览器观察 helper。

被 tools/web_observe_tool.py（用户可见的 web_observe 工具）和
loggers/diff_middleware.py（自动给 MCP 写动作附 diff 的中间件）共用，
避免重复实现"如何把 opthtml.js 注入 browser_evaluate 并解析返回值"。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

# opthtml.js 与本文件同目录，模块加载时一次性读入。
_THIS_DIR = Path(__file__).resolve().parent
OPTHTML_JS = (_THIS_DIR / "opthtml.js").read_text(encoding="utf-8")

# @playwright/mcp 提供的工具名
EVALUATE_TOOL_NAME = "browser_evaluate"


def find_evaluate_tool(mcp_tools) -> Optional[Any]:
    """在 mcp_tools 列表中查找 browser_evaluate；找不到返回 None。"""
    if not mcp_tools:
        return None
    for tool in mcp_tools:
        if getattr(tool, "name", "") == EVALUATE_TOOL_NAME:
            return tool
    return None


def build_evaluate_function(text_only: bool = False) -> str:
    """把 opthtml.js 包成 browser_evaluate 接受的 arrow function 字符串。"""
    text_only_js = "true" if text_only else "false"
    # 注意 opthtml.js 自身带模板字符串，不能用 f-string 嵌入，这里用拼接。
    return (
        "() => {\n"
        f"{OPTHTML_JS}\n"
        f"return optHTML({text_only_js});\n"
        "}"
    )


def normalize_evaluate_result(raw: Any) -> str:
    """把 browser_evaluate 的返回值统一成字符串。

    @playwright/mcp 不同版本返回结构不同：
    - 直接字符串
    - {"result": ...} / {"value": ...} / {"content": ...}
    - list[{"type": "text", "text": "..."}] (LangChain ToolMessage 风格)
    """
    if raw is None:
        return ""
    if isinstance(raw, str):
        stripped = raw.strip()
        if stripped.startswith("{") or stripped.startswith("["):
            try:
                return normalize_evaluate_result(json.loads(stripped))
            except (json.JSONDecodeError, ValueError):
                pass
        return raw
    if isinstance(raw, dict):
        for key in ("result", "value", "content", "data", "html"):
            if key in raw:
                return normalize_evaluate_result(raw[key])
        return json.dumps(raw, ensure_ascii=False)
    if isinstance(raw, list):
        parts = []
        for item in raw:
            if isinstance(item, dict) and item.get("type") == "text":
                parts.append(item.get("text", ""))
            else:
                parts.append(normalize_evaluate_result(item))
        return "\n".join(p for p in parts if p)
    return str(raw)


async def observe_simplified(
    eval_tool: Any,
    text_only: bool = False,
    timeout_seconds: float = 5.0,
) -> Optional[str]:
    """调用 browser_evaluate 注入 opthtml.js，返回 simplified HTML/文本字符串。

    失败（CSP 拒绝、超时、tab 不可用等）一律返回 None，由调用方决定降级策略。
    """
    import asyncio

    if eval_tool is None:
        return None
    try:
        raw = await asyncio.wait_for(
            eval_tool.ainvoke({"function": build_evaluate_function(text_only)}),
            timeout=timeout_seconds,
        )
    except (asyncio.TimeoutError, Exception):
        return None
    body = normalize_evaluate_result(raw)
    return body or None


# ── 瞬时文本监视器（toast / 错误提示 / loading 文案） ────────────────
# 移植自 GenericAgent/simphtml.py: temp_monitor_js + get_temp_texts
# 工作原理：每 450ms 扫一次 textNode，累积所有 ≥10 字符且不含下划线的前 20 字符。
# 动作完成后停止采集，返回"动作期间出现过、但现在已消失"的文本（toast 这类瞬态信号）。

_START_MONITOR_JS = """() => {
    if (window._tm && window._tm.id) clearInterval(window._tm.id);
    window._tm = { extract: () => {
        const texts = new Set();
        const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
        let node, t, s;
        while (node = walker.nextNode()) {
            if ((t = node.textContent.trim()) && t.length > 10 && !(s = t.substring(0, 20)).includes('_')) {
                texts.add(s);
            }
        }
        return texts;
    } };
    window._tm.init = window._tm.extract();
    window._tm.all = new Set();
    window._tm.id = setInterval(() => window._tm.extract().forEach(t => window._tm.all.add(t)), 450);
    return true;
}"""

_STOP_MONITOR_JS = """() => {
    if (!window._tm) return [];
    clearInterval(window._tm.id);
    const final = window._tm.extract();
    const newlySeen = [...window._tm.all].filter(t => !window._tm.init.has(t));
    let result;
    if (newlySeen.length < 8) {
        result = newlySeen;
    } else {
        result = newlySeen.filter(t => !final.has(t));
    }
    delete window._tm;
    return result;
}"""


async def start_transient_monitor(eval_tool: Any, timeout_seconds: float = 2.0) -> bool:
    """启动瞬时文本监视器。失败不抛异常，返回 False。"""
    import asyncio

    if eval_tool is None:
        return False
    try:
        await asyncio.wait_for(
            eval_tool.ainvoke({"function": _START_MONITOR_JS}),
            timeout=timeout_seconds,
        )
        return True
    except (asyncio.TimeoutError, Exception):
        return False


async def stop_transient_monitor(eval_tool: Any, timeout_seconds: float = 2.0) -> list[str]:
    """停止瞬时文本监视器并返回采集到的瞬时文本。失败返回空列表。"""
    import asyncio

    if eval_tool is None:
        return []
    try:
        raw = await asyncio.wait_for(
            eval_tool.ainvoke({"function": _STOP_MONITOR_JS}),
            timeout=timeout_seconds,
        )
    except (asyncio.TimeoutError, Exception):
        return []
    body = normalize_evaluate_result(raw)
    if not body:
        return []
    # body 可能是 JSON 字符串 "[...]" 或者已经是 list
    if isinstance(body, str):
        import json
        try:
            parsed = json.loads(body)
            if isinstance(parsed, list):
                return [str(x) for x in parsed if x]
        except (json.JSONDecodeError, ValueError):
            return []
    return []
