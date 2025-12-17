from langchain import agents
from langchain_community.chat_models import tongyi
from langchain_community.tools.playwright import (
    ClickTool,
    CurrentWebPageTool,
    ExtractHyperlinksTool,
    ExtractTextTool,
    GetElementsTool,
    NavigateBackTool,
    NavigateTool
)
from langchain.agents.middleware import HumanInTheLoopMiddleware
from context.context_manager import ContextManagerMiddleware
from langgraph.checkpoint.memory import InMemorySaver
from entity.my_state import MyState
from loggers.screen_logger import (
    log_agent_response,
    log_agent_start,
    log_playwright_tool_call,
    log_response_to_database
)
from prompt import system_prompt
from tools import (
    FillTextTool,
    GetAllElementTool,
    VLAnalysisTool,
    CaptureElementContextTool,
    delay_tool_call,
    read_archived_round,
    search_memory,
    search_knowledge_base
)
from tools.terminal_tools import terminal_read, terminal_write

# 单例缓存
_agent_cache = {}

def create_browser_agent(browser, model_name="qwen3-max", enable_thinking=True):
    """
    创建并配置浏览器自动化 Agent（单例模式）

    Args:
        browser: Playwright 浏览器实例
        model_name: 使用的模型名称
        enable_thinking: 是否启用思考模式
    """
    # 创建缓存 key，基于模型参数
    cache_key = f"{model_name}_{enable_thinking}"

    # 如果已缓存，直接返回（复用已编译的 agent）
    if cache_key in _agent_cache:
        return _agent_cache[cache_key]

    # 初始化工具集
    tools = [
        FillTextTool(async_browser=browser),
        ClickTool(async_browser=browser, playwright_timeout=10000, visible_only=False),
        CurrentWebPageTool(async_browser=browser),
        ExtractTextTool(async_browser=browser),
        NavigateTool(async_browser=browser),
        GetAllElementTool(async_browser=browser),
        VLAnalysisTool(),
        CaptureElementContextTool(async_browser=browser),
        NavigateBackTool(async_browser=browser),
        GetElementsTool(async_browser=browser),
        ExtractHyperlinksTool(async_browser=browser),
        read_archived_round,
        search_memory,
        terminal_read,
        terminal_write,
        search_knowledge_base,
    ]

    # 初始化模型
    model = tongyi.ChatTongyi(
        model_name=model_name,
        enable_thinking=enable_thinking,
    )

    # 初始化 ContextManagerMiddleware
    context_middleware = ContextManagerMiddleware(model=model,max_context_tokens=1280000,single_msg_limit = 128000)

    # 初始化 HITL 中间件
    hitl_middleware = HumanInTheLoopMiddleware(
        interrupt_on={
            "terminal_write": True,  # 拦截写操作，允许 Approve/Edit/Reject
            "terminal_read": True    # 拦截读操作，允许 Approve/Edit/Reject
        }
    )

    # 创建 Agent（最耗时的操作）
    browser_agent = agents.create_agent(
        system_prompt=system_prompt.system_prompt,
        state_schema=MyState,
        checkpointer= InMemorySaver(),
        model=model,
        tools=tools,
        middleware=[
            context_middleware,
            hitl_middleware,
            log_agent_start,
            log_playwright_tool_call,
            log_agent_response,
            log_response_to_database,
            delay_tool_call,
        ],
    )

    # 缓存已编译的 agent
    _agent_cache[cache_key] = browser_agent

    return browser_agent
