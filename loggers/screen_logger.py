import asyncio
import time
import os
from typing import Any
import dashscope
import dashscope.model
import dashscope.models
from playwright.async_api import Page
from langchain.agents.middleware import  after_agent,wrap_tool_call,types,before_agent
from langchain_community.tools.playwright.base import BaseBrowserTool
from langchain_community.tools.playwright import utils
from langchain.embeddings import Embeddings
from langchain.messages import HumanMessage
from sqlalchemy.orm import Session

from entity import MyState
from entity.agent_trace import AgentTrace, ResponseStatus
from database import engine
from utils import QwenEmbeddings



# 2. 中间件
@before_agent
async def log_agent_start(state: MyState, runtime) -> dict[str, Any]:
    return {"start_time": time.time()}


@after_agent(can_jump_to="end")
async def log_agent_response(state:types.StateT, runtime) -> None:
    """
    当代理成功完成任务时，记录所有响应的中间件。
    """
    if state is not None:
        session_id = state['messages'][0].id
        path = f"./screen/{session_id}/final_response_{time.time()}.txt"
        if not os.path.exists(os.path.dirname(path)):
            os.makedirs(os.path.dirname(path))
        with open(path,"w",encoding="utf-8") as f:
            for message in state['messages']:
                f.write(f"{message}\n")
        print("Final response logged.")

@after_agent(can_jump_to="end")
async def log_response_to_database(state:types.StateT, runtime) -> None:
    """
    当代理成功完成任务后，进行总结记录所有响应到database，便于之后进行查询。
    """
    if not state or 'messages' not in state:
        return

    messages = state['messages']
    
    # 1. 提取 User Query (第一条消息)
    user_query = messages[0].content if messages else ""
    
    # 2. 序列化整个链路 (Full Trace)
    serialized_trace = []
    tool_names_set = set()
    
    
    total_input_tokens = 0
    total_output_tokens = 0
    
    for msg in messages:
        msg_type = msg.type # human, ai, tool
        msg_data = {
            "role": msg_type,
            "content": msg.content,
            "additional_kwargs": msg.additional_kwargs
        }
        
        # 提取工具调用信息
        if msg_type == 'ai' and hasattr(msg, 'tool_calls') and msg.tool_calls:
            for tool_call in msg.tool_calls:
                tool_names_set.add(tool_call['name'])
        
        # 提取 Token 使用情况
        if msg_type == 'ai' and hasattr(msg, 'response_metadata'):
            usage = msg.response_metadata.get('token_usage', {})
            total_input_tokens += usage.get('input_tokens', 0)
            total_output_tokens += usage.get('output_tokens', 0)

        serialized_trace.append(msg_data)

    # 3. 提取最终回答 (最后一条 AI 消息)
    final_answer = messages[-1].content if messages and messages[-1].type == 'ai' else ""

    # 4. 生成 Embedding (需要配置 DashScopeEmbeddings)
    try:
        embeddings = QwenEmbeddings()
        vector = embeddings.embed_documents([user_query])
    except Exception as e:
        print(f"Embedding generation failed: {e}")
        vector = None

    # 在函数内部，计算执行耗时
    start_time = state.get("start_time")
    execution_duration = None
    if start_time is not None:
        execution_duration = time.time() - start_time  # 单位：秒，float
    # 5. 创建 AgentTrace 对象
    trace = AgentTrace(
        user_query=user_query,
        query_embedding=vector[0],
        full_trace=serialized_trace,
        final_answer=final_answer,
        tool_names=list(tool_names_set),
        token_usage={
            "input": total_input_tokens, 
            "output": total_output_tokens,
            "total": total_input_tokens + total_output_tokens
        },
        execution_duration=execution_duration, # 👈 新增这一行
        metadata_={
            "agent_runtime": str(runtime),
            "model": messages[-1].response_metadata.get('model_name') if messages and hasattr(messages[-1], 'response_metadata') else "unknown"
        },
        status=ResponseStatus.SUCCESS
    )

    # 6. 保存到数据库
    try:
        with Session(engine) as session:
            session.add(trace)
            session.commit()
            print(f"Agent trace logged to database with ID: {trace.id}")
    except Exception as e:
        print(f"Failed to log agent trace to database: {e}")


@wrap_tool_call
async def log_playwright_tool_call(
    request, handler
) :
    """
    当前工具调用的中间件。如果工具是 BaseBrowserTool 的实例，则截取当前页面的屏幕截图并将其保存到指定路径。
    该路径基于会话 ID、当前时间戳和工具调用 ID 进行命名，以确保唯一性。 
    """
    if isinstance(request.tool, BaseBrowserTool):
        response = await handler(request)
        tool:BaseBrowserTool = request.tool
        page:Page =await utils.aget_current_page(tool.async_browser)
        session_id = request.state['messages'][0].id
        path=f"./screen/{session_id}/{time.time()}{request.tool_call['id']}_call.png"
        await page.screenshot(path=path)
        print(f"Playwright Tool Called: {tool.name}")
        return response
    else:
        return await handler(request)

@wrap_tool_call
async def delay_tool_call(request, handler) :
    """
    设置工具间的延时，ms级别,确保网页加载完成  
    """
    if isinstance(request.tool, BaseBrowserTool):
        delay_ms = 500  # 设置延时为500毫秒
        await asyncio.sleep(delay_ms / 1000)  # 将毫秒转换为秒
        return await handler(request)
    else:
        return await handler(request)
        