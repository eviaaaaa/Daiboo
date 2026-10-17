"""MCP 客户端管理模块

职责：
1. 提供 MCPSessionManager 管理持久 MCP 会话（解决每次工具调用创建新 subprocess 的问题）
2. 提供 is_mcp_browser_tool() 辅助函数（供中间件判断）
"""

import asyncio
import os
import shutil

from loguru import logger
from contextlib import asynccontextmanager
from contextvars import ContextVar
from functools import wraps

from langchain_core.tools import StructuredTool

from langchain_mcp_adapters.tools import load_mcp_tools
from langchain_mcp_adapters.sessions import create_session
from utils.my_browser import DEBUGGING_PORT

_DEFAULT_PLAYWRIGHT_MCP_VERSION = "0.0.83"
_CODE_TOOLS = {"browser_run_code", "browser_run_code_unsafe"}


def _snapshot_mode() -> str:
    mode = (os.getenv("DAIBOO_BROWSER_SNAPSHOT_MODE") or "none").strip().lower()
    if mode not in {"none", "full"}:
        raise ValueError("DAIBOO_BROWSER_SNAPSHOT_MODE must be none or full")
    return mode


def _unsafe_code_enabled() -> bool:
    value = (os.getenv("DAIBOO_BROWSER_ALLOW_UNSAFE_CODE") or "false").strip().lower()
    if value not in {"true", "false", "1", "0"}:
        raise ValueError("DAIBOO_BROWSER_ALLOW_UNSAFE_CODE must be true or false")
    return value in {"true", "1"}


class BrowserSessionGate:
    """Serialize root operations; allow nested StructuredTool child tasks.

    Only the outer mutex acquisition creates an operation nonce. ContextVar
    inheritance alone never grants access: it must match the *active* owner.
    Callers inside a region must await their children before leaving it; do not
    spawn independent/fire-and-forget operations from an owned region.
    """

    def __init__(self):
        self._mutex = asyncio.Lock()
        self._operation: ContextVar[object | None] = ContextVar('browser_operation', default=None)
        self._owner = None

    @asynccontextmanager
    async def hold(self):
        inherited = self._operation.get()
        if inherited is not None and inherited is self._owner:
            yield
            return
        async with self._mutex:
            nonce = object()
            token = self._operation.set(nonce)
            self._owner = nonce
            try:
                yield
            finally:
                self._owner = None
                self._operation.reset(token)

    def wrap_tool(self, tool):
        # Real MCP adapters provide asynchronous StructuredTools. Copy rather
        # than mutating the raw adapter, retaining its complete input schema.
        if not isinstance(tool, StructuredTool) or tool.coroutine is None:
            return tool
        coroutine = tool.coroutine

        @wraps(coroutine)
        async def guarded(*args, **kwargs):
            async with self.hold():
                return await coroutine(*args, **kwargs)

        return tool.model_copy(update={'coroutine': guarded})


class MCPToolList(list):
    """List-compatible session tools, with a private fixed-code batch backend.

    Upstream run_code executes in the Node server (RCE-equivalent). Keep it out
    of the model's tool set unless explicitly opted in. The batch helper emits
    fixed code and serializes caller values as data; it never accepts JS code.
    Metadata comes from the connected server, not a presumed model/vendor.
    """

    def __init__(self, tools, *, snapshot_mode: str):
        self.session_gate = BrowserSessionGate()
        self.all_tools = {tool.name: self.session_gate.wrap_tool(tool) for tool in tools}
        self.snapshot_mode = snapshot_mode
        expose_code = _unsafe_code_enabled()
        super().__init__(tool for tool in self.all_tools.values()
                         if expose_code or tool.name not in _CODE_TOOLS)


def _playwright_mcp_package() -> str:
    version = (os.getenv("PLAYWRIGHT_MCP_VERSION") or "").strip()
    return f"@playwright/mcp@{version or _DEFAULT_PLAYWRIGHT_MCP_VERSION}"


def is_mcp_browser_tool(tool_name: str) -> bool:
    """判断工具名是否为 MCP 浏览器工具（名称以 browser_ 开头）"""
    return tool_name.startswith("browser_")


def _npx_command() -> str:
    env_command = (os.getenv("NPX_COMMAND") or "").strip()
    return env_command or shutil.which("npx.cmd") or shutil.which("npx") or "npx"


def _default_cdp_endpoint() -> str:
    return f"http://127.0.0.1:{DEBUGGING_PORT}"


# MCP 服务器连接配置
def _mcp_connection(cdp_endpoint: str | None = None):
    cdp_endpoint = (cdp_endpoint or "").strip() or _default_cdp_endpoint()
    npx_command = _npx_command()
    caps = (os.getenv("PLAYWRIGHT_MCP_CAPS") or "vision").strip()
    requested = [cap.strip() for cap in caps.split(",") if cap.strip()]
    if requested != ["none"] and any(cap not in {"vision", "pdf", "devtools"} for cap in requested):
        raise ValueError("PLAYWRIGHT_MCP_CAPS supports vision,pdf,devtools or none")
    args = [
        _playwright_mcp_package(), "--cdp-endpoint", cdp_endpoint,
        "--snapshot-mode", _snapshot_mode(),
    ]
    if requested and requested != ["none"]:
        args.append("--caps=" + ",".join(dict.fromkeys(requested)))
    return {"command": npx_command, "args": args, "transport": "stdio"}


@asynccontextmanager
async def create_persistent_mcp_session(cdp_endpoint: str | None = None):
    """创建持久 MCP 会话，返回工具列表。

    必须在 async with 中使用，session（subprocess）在退出时自动清理。

    用法：
        async with create_persistent_mcp_session() as mcp_tools:
            agent = await create_browser_agent(mcp_tools)
            # ... 使用 Agent ...
        # 退出后 MCP subprocess 自动关闭
    """
    connection = _mcp_connection(cdp_endpoint)
    async with create_session(connection) as session:
        await session.initialize()
        tools = MCPToolList(await load_mcp_tools(session), snapshot_mode=_snapshot_mode())
        logger.info("MCP 持久会话已建立，共 {} 个公开工具，snapshot={}", len(tools), tools.snapshot_mode)
        yield tools
    logger.info("MCP 持久会话已关闭")
