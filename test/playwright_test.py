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

from entity.my_state import MyState
from loggers.screen_logger import log_agent_response, log_agent_start, log_playwright_tool_call,log_response_to_database
from tools import (
    FillTextTool,
    GetAllElementTool,
    VLAnalysisTool,
    CaptureElementContextTool,
    delay_tool_call
)
from dotenv import load_dotenv

from utils.my_vcr import MyVcr
if TYPE_CHECKING:
    from playwright.async_api import Browser as AsyncBrowser
    from playwright.sync_api import Browser as SyncBrowser
load_dotenv()
QFNU_USERNAME=os.environ["QFNU_USERNAME"]
QFNU_PASSWORD=os.environ["QFNU_PASSWORD"]

@MyVcr.use_cassette("test_playwright_agent.yaml")    
async def test_playwright():
    """
    主函数
    """
    async with async_playwright() as p:
        async with await p.chromium.launch() as browser:
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
            inputs={
                "messages": [
                    # HumanMessage(
                    #     content= """
                    #     你的任务：
                    #     1.你必须先回答”1024杯水有一瓶毒水，毒水偏重，你有一个天平，你如何找出毒水？“
                    #     2.然后在同意请求中调用工具完成任务。打开 https://www.saucedemo.com/，然后输入账号:standard_user，密码：secret_sauce,然后点击登录，之后告诉我页面中有什么
                    #     """
                    # ),
                    HumanMessage(
                        content=f"""
                        你是一个网页自动化助手。请按以下步骤完成教务系统登录：

                        **步骤 1: 导航与页面分析**
                        1. 打开登录页面：http://zhjw.qfnu.edu.cn/jsxsd/framework/xsMain.jsp
                        2. 使用 get_all_element_tool 查看页面结构，找到表单字段的ID

                        **步骤 2: 填写表单（每次只填一个字段）**
                        3. 填写账号字段 #userAccount：{QFNU_USERNAME}
                        4. 填写密码字段 #userPassword：{QFNU_PASSWORD}

                        **步骤 3: 验证码识别**
                        5. 使用 capture_element_context 截取验证码图片
                        - element_description 参数使用: "#SafeCodeImg" 或 "img#SafeCodeImg"
                        - 不要传入 selector 参数
                        6. 使用 vl_analysis_tool 分析截图，识别验证码内容
                        - prompt 参数: "识别这张验证码图片中的字符，只返回4位数字或字母，不要有其他说明"
                        7. 填写验证码字段 #RANDOMCODE

                        **步骤 4: 提交与验证**
                        8. 点击登录按钮（使用 CSS 选择器或文本"登录"）
                        9. 使用 extract_text 获取登录后页面内容

                        **重要规则：**
                        - 每次只调用一个工具
                        - 使用 CSS 选择器时，element_description 直接传入如 "#elementId" 或 "img#SafeCodeImg"
                        - capture_element_context 只接受 element_description、context_size、include_surrounding_text、screenshot_dir 参数
                        - 不要传入不存在的参数如 selector
                        """
                    )
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
    asyncio.run(test_playwright())