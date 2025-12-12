import os

import asyncio
import pprint
from typing import TYPE_CHECKING

from langchain import agents
from langchain.messages import HumanMessage,SystemMessage
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
from loggers.screen_logger import log_agent_response, log_agent_start, log_playwright_tool_call,log_response_to_database
from prompt import system_prompt
from tools import delay_tool_call
import rag
from rag import hybrid_search_service
from rag import document_rag_pgvector
from rag import question_rag_pgvector
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
            # 1. 使用封装函数获取并清理数据
            rag_docs = document_rag_pgvector.query_document_from_pgvector(query, top_k=1)
            rag_exps = question_rag_pgvector.get_question_from_pgvector(query, top_k=1)

            # 2. 手动格式化为清晰的字符串
            docs_str = "\n\n".join([f"文档片段 {i+1}:\n{doc.content}" for i, doc in enumerate(rag_docs)])
            
            exps_str = ""
            for i, trace in enumerate(rag_exps):
                exps_str += f"历史案例 {i+1}:\n"
                exps_str += f"用户问题: {trace.user_query}\n"
                exps_str += f"执行过程: {str(trace.full_trace)}\n\n"

            context_text = f"""
                以下是可能有帮助的参考资料：

                【相关文档知识库】
                {docs_str}

                【相关历史成功案例】
                {exps_str}
                """
            inputs={
                "messages": [
                    SystemMessage(content=system_prompt.system_prompt),
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
