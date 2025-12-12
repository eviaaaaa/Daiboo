import os

import asyncio
import pprint
import random
from typing import TYPE_CHECKING

from langchain.messages import HumanMessage,SystemMessage
from playwright.async_api import async_playwright
from sqlalchemy.orm import Session

from database import engine
from entity.agent_trace import AgentTrace
from entity.rag_document import RagDocument
from prompt import system_prompt, task_prompt
from rag import hybrid_search_service, document_rag_pgvector, question_rag_pgvector
from dotenv import load_dotenv

from utils.my_browser import launch_or_connect_browser
from agent_factory import create_browser_agent

if TYPE_CHECKING:
    from playwright.async_api import Browser as AsyncBrowser
    from playwright.sync_api import Browser as SyncBrowser

 

async def main():
    """
    主函数 - 交互式版本，持续接收用户输入直到输入 'exit' 或 'quit'
    """
    async with async_playwright() as p:
        async with await launch_or_connect_browser(p) as browser:
            # 使用工厂函数创建 agent
            browser_agent = create_browser_agent(browser)

            print("=" * 60)
            print("NexusSurf 浏览器自动化助手")
            print("输入 'exit' 或 'quit' 退出程序")
            print("=" * 60)

            while True:
                # 从用户输入读取查询
                query = input("\n请输入您的查询：").strip()

                # 检查是否退出
                if query.lower() in ['exit', 'quit']:
                    print("退出程序")
                    break

                if not query:
                    print("查询不能为空，请重新输入")
                    continue

                print("\n用户查询：", query)

                # 1. 使用封装函数获取并清理数据
                rag_docs = document_rag_pgvector.query_document_from_pgvector(query, top_k=3)
                rag_exps = question_rag_pgvector.get_question_from_pgvector(query, top_k=3)

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
                inputs = {
                    "messages": [
                        HumanMessage(content=f"{context_text}\n\n用户问题：{query}")
                    ]
                }
                print("\n🚀 开始流式执行任务...")
                # 增加递归限制以支持更长的交互流程
                config = {"recursion_limit": 80}
                async for chunk in browser_agent.astream(inputs, config=config, stream_mode="updates"):
                    mes = chunk.__str__()
                    pprint.pprint(mes[:2000])  # 只打印前2000字符，防止输出过长
                    print("\n" + "=" * 50 + "\n")


if __name__ == "__main__":
    asyncio.run(main())
