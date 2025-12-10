import os

import asyncio
import pprint
from typing import TYPE_CHECKING

from langchain import agents
from langchain.messages import HumanMessage
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
from playwright.async_api import async_playwright
from sqlalchemy.orm import Session

from database import engine
from entity.agent_trace import AgentTrace
from entity.my_state import MyState
from entity.rag_document import RagDocument
from loggers.screen_logger import log_agent_response, log_agent_start, log_playwright_tool_call,delay_tool_call,log_response_to_database
import rag
from rag import hybrid_search_service
from tools import (
    FillTextTool,
    GetPageImgTool,
    GetAllElementTool,
    VLAnalysisTool,
    CaptureElementContextTool
)
from dotenv import load_dotenv
from utils.my_browser import launch_or_connect_browser
if TYPE_CHECKING:
    from playwright.async_api import Browser as AsyncBrowser
    from playwright.sync_api import Browser as SyncBrowser
load_dotenv()
QFNU_USERNAME=os.environ["QFNU_USERNAME"]
QFNU_PASSWORD=os.environ["QFNU_PASSWORD"]
os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"
    

async def test_rag():
    """
    主函数
    """
    async with async_playwright() as p:
        async with await launch_or_connect_browser(p) as browser:
            tools = [
                FillTextTool(async_browser=browser),
                ClickTool(async_browser=browser, playwright_timeout=10000,visible_only=False),
                CurrentWebPageTool(async_browser=browser),
                ExtractTextTool(async_browser=browser),
                NavigateTool(async_browser=browser),
                GetAllElementTool(async_browser=browser),
                VLAnalysisTool(),
                CaptureElementContextTool(async_browser=browser),
                NavigateBackTool(async_browser=browser),
                GetElementsTool(async_browser=browser),
                ExtractHyperlinksTool(async_browser=browser),
            ]

            model = tongyi.ChatTongyi(
                model_name="qwen3-max",
                enable_thinking=True,
            )
            ###
            # 创建 agent
            browser_agent = agents.create_agent(
                state_schema=MyState,
                model=model,
                tools=tools,
                middleware=[
                    log_agent_start,
                    delay_tool_call,
                    log_playwright_tool_call,
                    log_agent_response,
                    log_response_to_database,
                ],
            )
            query = f"""
                        你的任务：
                        1.你必须先回答”1024杯水有一瓶毒水，毒水偏重，你有一个天平，你如何找出毒水？“
                        2.然后在同意请求中调用工具完成任务。打开 https://www.saucedemo.com/，然后输入账号:standard_user，密码：secret_sauce,然后点击登录，之后告诉我页面中有什么
                        """
            with Session(engine) as session:
                hybrid_search = hybrid_search_service.HybridSearchService(session)
                rag_doc = hybrid_search.search(RagDocument, query,1)
                rag_exp = hybrid_search.search(AgentTrace, query,1)
            context_text = f"""\
                这是可能有帮助的相关文档：
                {rag_doc}

                这是可能有帮助的相关问答：
                {rag_exp}
                """
            inputs={
                "messages": [
                    HumanMessage(content=f"{context_text}\n\n用户问题：{query}")
                ]
            }
            print("🚀 开始流式执行任务...")
            # 增加递归限制以支持更长的交互流程
            config = {"recursion_limit": 50}
            async for chunk in browser_agent.astream(inputs, config=config, stream_mode="updates"):
                mes = chunk.__str__()
                pprint.pprint(mes[:2000])  # 只打印前2000字符，防止输出过长
                print("\n"+"="*50+"\n")


if __name__ == "__main__":
    asyncio.run(test_rag())
