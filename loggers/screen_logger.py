import asyncio
import time
import os
from typing import Any
import jieba
from playwright.async_api import Page
from langchain.agents.middleware import  after_agent,wrap_tool_call,types,before_agent
from langchain_community.tools.playwright.base import BaseBrowserTool
from langchain_community.tools.playwright import utils
from sqlalchemy.orm import Session
from sqlalchemy import func

from entity import MyState
from entity.agent_trace import AgentTrace, ResponseStatus
from database import engine
from utils import  qwen_embeddings
from rag.question_rag_pgvector import save_agent_trace_to_pgvector



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
    
    # 1. 提取 User Query (寻找第一条 HumanMessage 并清洗 RAG 上下文)
    user_query = ""
    for msg in messages:
        if msg.type == 'human':
            # 尝试清洗 RAG 上下文，避免 Embedding 被污染
            if "用户问题：" in msg.content:
                user_query = msg.content.split("用户问题：")[-1].strip()
            else:
                user_query = msg.content
            break
            
    if not user_query and messages:
        # Fallback: 避免取到 SystemMessage
        user_query = messages[1].content if len(messages) > 1 else messages[0].content
    
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
        embeddings = qwen_embeddings
        vector = embeddings.embed_documents([user_query])
    except Exception as e:
        print(f"Embedding generation failed: {e}")
        vector = None

    # 在函数内部，计算执行耗时
    start_time = state.get("start_time")
    execution_duration = None
    if start_time is not None:
        execution_duration = time.time() - start_time  # 单位：秒，float
    
    # 中文分词
    seg_list = jieba.cut(user_query)
    seg_content = " ".join(seg_list)

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
        status=ResponseStatus.SUCCESS,
        fts_vector=func.to_tsvector('simple', seg_content)
    )

    # 6. 保存到数据库
    save_agent_trace_to_pgvector(trace)


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
        try:
            # 增加超时时间到 5000ms (5秒)，并捕获异常，避免截图失败导致整个任务失败
            # 如果页面加载很慢，可以适当增加，或者设置为 full_page=False
            await page.screenshot(path=path, timeout=5000)
        except Exception as e:
            print(f"Warning: Failed to take screenshot for tool {tool.name}: {e}")
        
        print(f"Playwright Tool Called: {tool.name}")
        return response
    else:
        return await handler(request)

        