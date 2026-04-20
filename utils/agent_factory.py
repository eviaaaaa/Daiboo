from langchain import agents
from langchain.agents.middleware import HumanInTheLoopMiddleware
from typing import TYPE_CHECKING, Any
from context.context_manager import ContextManagerMiddleware
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.prebuilt.tool_node import ToolNode
from entity.my_state import MyState
from loggers.screen_logger import (
    log_agent_response,
    log_agent_start,
    log_playwright_tool_call,
    log_response_to_database
)
from loggers.experience_middleware import log_experience
from prompt import system_prompt
from tools import (
    VLAnalysisTool,
    CaptureElementContextTool,
    delay_tool_call,
    search_documents,
    search_task_experience
)
from tools.terminal_tools import terminal_read, terminal_write
from utils.qwen_model import create_qwen_model

if TYPE_CHECKING:
    from langgraph.graph.state import CompiledStateGraph

# 单例缓存
_agent_cache: dict[str, "CompiledStateGraph"] = {}

def get_agent_tools(mcp_tools: Any, screenshot_helper: Any = None) -> list[Any]:
    """获取工具列表

    参数：
        mcp_tools: MCP 浏览器工具列表
        screenshot_helper: ScreenshotHelper 实例，供 CaptureElementContextTool 使用
    """
    return [
        *mcp_tools,                                                  # MCP 浏览器工具
        CaptureElementContextTool(helper=screenshot_helper),         # 重写版
        VLAnalysisTool(),                                            # 保留
        terminal_read,                                               # 保留
        terminal_write,                                              # 保留
        search_documents,                                            # 保留
        search_task_experience,                                      # 保留
    ]

async def create_browser_agent(
    mcp_tools: Any,
    screenshot_helper: Any = None,
    model_name: str = "qwen3.5-plus",
    enable_thinking: bool = True,
) -> "CompiledStateGraph":
    """
    创建并配置浏览器自动化 Agent（单例模式）

    参数：
        mcp_tools: MCP 浏览器工具列表
        screenshot_helper: ScreenshotHelper 实例
        model_name: 使用的模型名称
        enable_thinking: 是否启用思考模式
    """
    # 创建缓存键，基于模型参数
    cache_key = f"{model_name}_{enable_thinking}"

    # 如果已缓存，直接返回（复用已编译的 Agent）
    if cache_key in _agent_cache:
        return _agent_cache[cache_key]

    # 初始化工具集
    tools = get_agent_tools(mcp_tools, screenshot_helper)

    # 初始化模型
    model = create_qwen_model(
        model_name=model_name,
        temperature=0.0,
        request_timeout=5000,
    )

    # 初始化 ContextManagerMiddleware
    context_middleware = ContextManagerMiddleware(model=model)

    # 初始化 HITL 中间件
    hitl_middleware = HumanInTheLoopMiddleware(
        interrupt_on={
            "terminal_write": True,  # 拦截写操作，允许批准/编辑/拒绝
            "terminal_read": True    # 拦截读操作，允许批准/编辑/拒绝
        }
    )

    # 创建 Agent（最耗时的操作）
    browser_agent = agents.create_agent(
        system_prompt=system_prompt.system_prompt,
        state_schema=MyState,
        checkpointer=InMemorySaver(),
        model=model,
        tools=tools,
        middleware=[
            context_middleware,
            hitl_middleware,
            log_agent_start,
            log_playwright_tool_call,
            log_agent_response,
            log_response_to_database,  # 先记录链路
            log_experience,            # 再异步总结经验
            delay_tool_call,
        ],
    )

    # 修补 ToolNode：捕获所有工具执行异常并返回为 ToolMessage
    # 默认只捕获 ToolInvocationError（参数校验），MCP 执行错误会直接崩溃 Agent
    for node in browser_agent.nodes.values():
        bound = getattr(node, 'bound', None)
        if isinstance(bound, ToolNode):
            bound._handle_tool_errors = True

    # 缓存已编译的 Agent
    _agent_cache[cache_key] = browser_agent

    return browser_agent
