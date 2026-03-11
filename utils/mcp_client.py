"""MCP 客户端管理模块

职责：
1. 提供 MCPSessionManager 管理持久 MCP 会话（解决每次工具调用创建新 subprocess 的问题）
2. 提供 is_mcp_browser_tool() 辅助函数（供中间件判断）
"""

import logging
from contextlib import asynccontextmanager

from langchain_mcp_adapters.tools import load_mcp_tools
from langchain_mcp_adapters.sessions import create_session

logger = logging.getLogger(__name__)


def is_mcp_browser_tool(tool_name: str) -> bool:
    """判断工具名是否为 MCP 浏览器工具（名称以 browser_ 开头）"""
    return tool_name.startswith("browser_")


# MCP 服务器连接配置
def _mcp_connection(cdp_endpoint: str = "http://127.0.0.1:9222"):
    return {
        "command": "npx.cmd",  # Windows 用 npx.cmd
        "args": ["@playwright/mcp@latest", "--cdp-endpoint", cdp_endpoint],
        "transport": "stdio",
    }


@asynccontextmanager
async def create_persistent_mcp_session(cdp_endpoint: str = "http://127.0.0.1:9222"):
    """创建持久 MCP 会话，返回工具列表。

    必须在 async with 中使用，session（subprocess）在退出时自动清理。

    用法：
        async with create_persistent_mcp_session() as mcp_tools:
            agent = await create_browser_agent(mcp_tools)
            # ... 使用 agent ...
        # 退出后 MCP subprocess 自动关闭
    """
    connection = _mcp_connection(cdp_endpoint)
    async with create_session(connection) as session:
        await session.initialize()
        tools = await load_mcp_tools(session)
        logger.info(f"MCP 持久会话已建立，共 {len(tools)} 个工具")
        yield tools
    logger.info("MCP 持久会话已关闭")
