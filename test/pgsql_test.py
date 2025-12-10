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
import pytest
import vcr

from entity import MyState
from loggers.screen_logger import log_response_to_database,log_agent_start
from langchain.agents.middleware import ModelCallLimitMiddleware

from tools import (
    FillTextTool,
    GetPageImgTool,
    GetAllElementTool,
    VLAnalysisTool,
    CaptureElementContextTool
)
from dotenv import load_dotenv

from utils.my_vcr import MyVcr
if TYPE_CHECKING:
    from playwright.async_api import Browser as AsyncBrowser
    from playwright.sync_api import Browser as SyncBrowser
load_dotenv()
QFNU_USERNAME=os.environ["QFNU_USERNAME"]
QFNU_PASSWORD=os.environ["QFNU_PASSWORD"]

@MyVcr.use_cassette('test/vcr_cassettes/test_browser_agent.yaml')    
async def test_request():

    async with async_playwright() as p:
        async with await p.chromium.launch()as browser:
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
                    log_response_to_database,
                ],
            )
            inputs={
                "messages": [
                    HumanMessage(
                        content= """
                        你的任务：
                        1.你必须先回答”1024杯水有一瓶毒水，毒水偏重，你有一个天平，你如何找出毒水？“
                        2.然后在同意请求中调用工具完成任务。打开 https://www.saucedemo.com/，然后输入账号:standard_user，密码：secret_sauce,然后点击登录，之后告诉我页面中有什么
                        """
                    ),
                    # HumanMessage(
                    #     content=f"""500+600=？
                    #     """
                    # )
                ]
            }
            print("🚀 开始流式执行任务...")
            # 增加递归限制以支持更长的交互流程
            config = {"recursion_limit": 50}
            async for chunk in browser_agent.astream(inputs, config=config, stream_mode="updates"):
                mes = chunk.__str__()
                pprint.pprint(mes[:2000])  # 只打印前2000字符，防止输出过长
                print("\n"+"="*50+"\n")
