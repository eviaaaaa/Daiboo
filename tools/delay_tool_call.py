import asyncio
from langchain.agents.middleware import  wrap_tool_call
from langchain_community.tools.playwright.base import BaseBrowserTool

@wrap_tool_call
async def delay_tool_call(request, handler) :
    """
    设置工具间的延时，ms级别,确保网页加载完成  
    """
    if isinstance(request.tool, BaseBrowserTool):
        delay_ms = 500  # 设置延时为500毫秒
        await asyncio.sleep(delay_ms / 1000)  # 将毫秒转换为秒
        return await handler(request)
    else:
        return await handler(request)