"""web_observe 工具：基于 simphtml 的 LLM-friendly 页面观察。

定位：作为 @playwright/mcp 的 `browser_snapshot` 的补充，专攻：
- 跨 iframe / Shadow DOM 内容内联
- 浮窗广告 / 被遮挡内容自动剔除
- 字符预算控制（默认 35000）
- 表单当前值落入属性，autofill 字段保护
- 透明 wrapper 的 bbox 修复

不替换 browser_snapshot：snapshot 的 ref-based 精确点击仍然是它的强项。

实现路径：通过 MCP 加载好的 `browser_evaluate` 工具注入 `tools/_simphtml/opthtml.js`，
拿回简化后的 HTML 字符串后做 BeautifulSoup 二次清洗 + 预算式 smart_truncate。

源算法来自 https://github.com/lsdefine/GenericAgent (MIT)。详见
docx/genericagent_investigation.md 与 docx/genericagent_improvement_plan.md。
"""
from __future__ import annotations

import logging
import re
from typing import Any, Optional, Type

from langchain_core.callbacks import AsyncCallbackManagerForToolRun
from langchain_core.tools import BaseTool
from pydantic import BaseModel, ConfigDict, Field

from tools._simphtml import (
    find_evaluate_tool,
    observe_simplified,
    optimize_html_for_tokens,
    smart_truncate,
)

logger = logging.getLogger(__name__)


class WebObserveToolInput(BaseModel):
    """web_observe 工具的输入参数。"""

    model_config = ConfigDict(extra="forbid")

    text_only: bool = Field(
        default=False,
        description=(
            "True 输出纯文本（input/select 显式标注为 [INPUT type=... name=...]，"
            "块级元素分行）；False 输出简化 HTML（保留结构便于精确定位）。"
            "想快速读页面文本时选 True，想后续基于结构操作时选 False。"
        ),
    )

    max_chars: int = Field(
        default=35000,
        ge=2000,
        le=200000,
        description="输出字符上限，超出时通过 smart_truncate 递归裁切。",
    )


class WebObserveTool(BaseTool):
    """页面整体观察：跨 iframe / Shadow DOM、剔除浮窗、字符预算可控。

    与 browser_snapshot 的差别：
    - browser_snapshot 输出 accessibility tree，适合「已知要点击什么、需要 ref」
    - web_observe 输出简化 HTML/文本，适合「先看清页面再决定下一步」
    - browser_snapshot 看不到 iframe 内容；web_observe 可以
    """

    name: str = "web_observe"
    description: str = (
        "获取当前活跃标签页的简化 HTML 视图：跨 iframe 与 Shadow DOM 内容内联、"
        "自动剔除浮窗广告与被遮挡内容、表单当前值落入属性、字符预算可控。"
        "适合「先看清整页再决定下一步」的场景；想精确点击元素请改用 browser_snapshot。"
        "参数 text_only=True 时输出纯文本（更省 token），默认 False 输出 HTML 结构。"
    )

    args_schema: Type[BaseModel] = WebObserveToolInput

    # 通过构造参数注入 MCP 工具列表，从中挑出 browser_evaluate。
    mcp_tools: Any = Field(default=None, exclude=True)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        if self.mcp_tools is None:
            logger.warning(
                "WebObserveTool 在 mcp_tools=None 下创建。"
                "运行时若仍为 None 将返回错误结果。"
            )

    @staticmethod
    def _post_process_html(html: str, max_chars: int) -> tuple[str, bool]:
        """对 simplified HTML 做 BeautifulSoup 清洗 + iframe 标记还原 + 预算裁切。

        返回 (final_html, truncated)。
        """
        soup = optimize_html_for_tokens(html)
        # opthtml.js 在跨 iframe inline 时把 <iframe> 替换成 <div data-tag="iframe">，
        # 这里还原成 iframe 标签，方便 LLM 理解层级。
        for div in soup.select('div[data-tag="iframe"]'):
            div.name = "iframe"
            del div["data-tag"]
        rendered = str(soup)
        truncated = False
        if len(rendered) > max_chars:
            soup = smart_truncate(soup, max_chars)
            rendered = str(soup)
            truncated = True
        return rendered, truncated

    @staticmethod
    def _post_process_text(text: str) -> str:
        """text_only=True 时的简单清洗：合并空白、去行首空格、去多空行。"""
        text = re.sub(r" {2,}", " ", text)
        text = re.sub(r"^ +", "", text, flags=re.M)
        text = re.sub(r"(\n\s*){3,}", "\n\n", text)
        return text.strip()

    # ── 工具入口 ──────────────────────────────────────────────────

    def _run(self, **kwargs) -> str:
        raise NotImplementedError("web_observe 仅支持异步调用，请用 _arun")

    async def _arun(
        self,
        *,
        text_only: bool = False,
        max_chars: int = 35000,
        run_manager: Optional[AsyncCallbackManagerForToolRun] = None,
        **_,
    ) -> dict:
        """异步执行：注入 opthtml.js 到当前 tab，返回简化结果。"""
        eval_tool = find_evaluate_tool(self.mcp_tools)
        if eval_tool is None:
            return {
                "ok": False,
                "error": "browser_evaluate 工具未在 MCP 工具列表中找到",
                "hint": "检查 utils/agent_factory.py: get_agent_tools() 是否传入 mcp_tools。",
            }

        body = await observe_simplified(eval_tool, text_only=text_only)
        if body is None:
            return {
                "ok": False,
                "error": "browser_evaluate 调用失败或返回空",
                "hint": (
                    "可能原因：CSP 禁止 eval / 当前 tab 是 chrome:// 内部页 / "
                    "页面是 about:blank / MCP 会话繁忙。可先 browser_snapshot 兜底，"
                    "或先 browser_navigate 到目标 URL 后重试。"
                ),
            }

        if text_only:
            cleaned = self._post_process_text(body)
            return {
                "ok": True,
                "mode": "text",
                "char_count": len(cleaned),
                "truncated": False,
                "content": cleaned,
            }

        rendered, truncated = self._post_process_html(body, max_chars)
        return {
            "ok": True,
            "mode": "html",
            "char_count": len(rendered),
            "truncated": truncated,
            "content": rendered,
        }
