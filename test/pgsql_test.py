"""
测试日志中间件功能
测试 log_agent_start 和 log_response_to_database 中间件的组合使用
"""
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
    ExtractTextTool,
    NavigateTool,
)
from playwright.async_api import async_playwright
import pytest
from sqlalchemy.orm import Session

from entity import MyState
from entity.agent_trace import AgentTrace
from database import engine
from loggers.screen_logger import log_response_to_database, log_agent_start
from tools import FillTextTool, GetAllElementTool
from dotenv import load_dotenv
from utils.my_vcr import MyVcr

if TYPE_CHECKING:
    from playwright.async_api import Browser as AsyncBrowser
    
load_dotenv()


@MyVcr.use_cassette('test/vcr_cassettes/test_middleware_logging.yaml')    
async def test_middleware_logging():
    """
    测试 log_agent_start 和 log_response_to_database 中间件的组合功能
    验证：
    1. log_agent_start 记录任务开始
    2. log_response_to_database 记录每次模型响应到数据库
    3. 任务执行后可以从数据库查询到完整的执行记录
    """
    print("=" * 80)
    print("测试日志中间件：log_agent_start + log_response_to_database")
    print("=" * 80)
    
    # 记录测试开始前的数据库记录数
    with Session(engine) as session:
        initial_count = session.query(AgentTrace).count()
        print(f"\n📊 测试开始前数据库中的记录数: {initial_count}")
    
    async with async_playwright() as p:
        async with await p.chromium.launch(headless=True) as browser:
            # 创建最小化的工具集
            tools = [
                NavigateTool(async_browser=browser),
                GetAllElementTool(async_browser=browser),
                FillTextTool(async_browser=browser),
                ClickTool(async_browser=browser, playwright_timeout=10000, visible_only=False),
                CurrentWebPageTool(async_browser=browser),
                ExtractTextTool(async_browser=browser),
            ]

            # 创建模型
            model = tongyi.ChatTongyi(
                model_name="qwen3-max",
                temperature=0.0,
            )
            
            # 创建 agent，配置日志中间件
            browser_agent = agents.create_agent(
                state_schema=MyState,
                model=model,
                tools=tools,
                middleware=[
                    log_agent_start,           # 记录任务开始
                    log_response_to_database,  # 记录每次响应
                ],
            )
            
            # 创建简单的测试任务
            inputs = {
                "messages": [
                    HumanMessage(
                        content="""
                        简单测试任务：
                        打开 https://www.baidu.com/，然后告诉我页面标题是什么
                        """
                    )
                ]
            }
            
            print("\n🚀 开始执行任务...")
            print(f"📝 任务内容: 访问 example.com 并获取页面标题")
            
            # 执行任务
            config = {"recursion_limit": 20}
            step_count = 0
            
            async for chunk in browser_agent.astream(inputs, config=config, stream_mode="updates"):
                step_count += 1
                print(f"\n--- 步骤 {step_count} ---")
                # 只打印关键信息
                chunk_str = str(chunk)
                if len(chunk_str) > 500:
                    print(chunk_str[:500] + "...")
                else:
                    print(chunk_str)
            
            print(f"\n✅ 任务执行完成，共 {step_count} 个步骤")
    
    # 验证数据库记录
    print("\n" + "=" * 80)
    print("验证数据库记录")
    print("=" * 80)
    
    with Session(engine) as session:
        final_count = session.query(AgentTrace).count()
        new_records = final_count - initial_count
        
        print(f"\n📊 测试后数据库中的记录数: {final_count}")
        print(f"📈 新增记录数: {new_records}")
        
        if new_records > 0:
            # 获取最新的记录
            latest_trace = session.query(AgentTrace).order_by(
                AgentTrace.created_at.desc()
            ).first()
            
            print(f"\n✅ 中间件工作正常！")
            print(f"📝 最新记录信息:")
            print(f"   - Session ID: {latest_trace.session_id}")
            print(f"   - User Query: {latest_trace.user_query[:100]}...")
            print(f"   - Created At: {latest_trace.created_at}")
            print(f"   - Full Trace Length: {len(str(latest_trace.full_trace))} 字符")
            
            assert new_records >= 1, "应该至少有一条新的日志记录"
            print(f"\n✨ 测试通过：日志中间件成功记录了 {new_records} 条数据")
        else:
            print("\n❌ 警告：没有新增记录，中间件可能未正常工作")
            assert False, "中间件应该记录至少一条数据"
    
    print("\n" + "=" * 80)
    print("测试完成")
    print("=" * 80)


if __name__ == "__main__":
    asyncio.run(test_middleware_logging())
