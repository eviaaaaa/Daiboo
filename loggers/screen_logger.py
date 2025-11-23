import time
from langchain.agents.middleware import  after_agent, AgentMiddleware,types,wrap_tool_call
from pprint import pprint
from langchain_community.tools.playwright.base import BaseBrowserTool
from playwright.async_api import Page
from langchain_community.tools.playwright import utils
@after_agent(can_jump_to="end")
async def log_agent_response(state:types.StateT, runtime) -> None:
    """
    当代理成功完成任务时，记录最终响应的中间件。
    """
    if state is not None:
        session_id = state['messages'][0].id
        with open(f"./{session_id}/final_response_{time.time()}.txt","w",encoding="utf-8") as f:
            for message in state['messages']:
                f.write(f"{message}\n")
        print("Final response logged.")
    


@wrap_tool_call
async def log_playwright_tool_call(
    request, handler
) :
    """
    当前工具调用的中间件。如果工具是 BaseBrowserTool 的实例，则截取当前页面的屏幕截图并将其保存到指定路径。
    该路径基于会话 ID、当前时间戳和工具调用 ID 进行命名，以确保唯一性。 
    """
    if not isinstance(request.tool, BaseBrowserTool):
        print("Not a BaseBrowserTool, skipping logging.")
        return await handler(request)
    else :    
        response = await handler(request)
        tool:BaseBrowserTool = request.tool
        page:Page =await utils.aget_current_page(tool.async_browser)
        session_id = request.state['messages'][0].id
        await page.screenshot(path=f"./{session_id}/{time.time()}{request.tool_call['id']}_call.png")
        print(f"Playwright Tool Called: {tool.name}")
        return response