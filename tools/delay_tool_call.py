"""Optional compatibility pacing; Playwright auto-wait is the default."""
import asyncio
import os
from langchain.agents.middleware import wrap_tool_call
from utils.mcp_client import is_mcp_browser_tool


@wrap_tool_call
async def delay_tool_call(request, handler):
    if is_mcp_browser_tool(getattr(request.tool, "name", "")):
        value = (os.getenv("BROWSER_ACTION_DELAY_MS") or "0").strip()
        try:
            delay_ms = int(value)
        except ValueError as exc:
            raise ValueError("BROWSER_ACTION_DELAY_MS must be an integer in 0..10000") from exc
        if not 0 <= delay_ms <= 10000:
            raise ValueError("BROWSER_ACTION_DELAY_MS must be an integer in 0..10000")
        if delay_ms:
            await asyncio.sleep(delay_ms / 1000)
    return await handler(request)
