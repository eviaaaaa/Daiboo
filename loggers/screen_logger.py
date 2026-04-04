import asyncio
import time
import os
from typing import Any
from langchain.agents.middleware import after_agent, wrap_tool_call, types, before_agent
from sqlalchemy.orm import Session

from rag.question_rag_pgvector import save_agent_trace_to_pgvector
from entity import MyState
from entity.agent_trace import AgentTrace, ResponseStatus
from database import engine
from utils.mcp_client import is_mcp_browser_tool
from utils.qwen_model import normalize_content



# 2. 中间件
@before_agent
async def log_agent_start(state: MyState, runtime) -> dict[str, Any]:
    # 初始化或递增轮次号
    current_turn = state.get('turn_number', 0) + 1
    return {
        "start_time": time.time(),
        "turn_number": current_turn
    }


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
    链路记录中间件：每轮对话追加一条新记录到 AgentTrace 表（审计日志）
    采用追加更新机制，同一 session 可以有多条记录
    """
    if not state or 'messages' not in state:
        return

    messages = state['messages']
    
    # 1. 获取 session_id
    session_id = state.get('configurable', {}).get('thread_id')
    if not session_id:
        session_id = messages[0].id if messages else None
    
    if not session_id:
        print("⚠️ 无法获取 session_id，跳过链路记录")
        return
    
    # 2. 提取 User Query（最后一条 HumanMessage）
    user_query = ""
    for msg in reversed(messages):
        if msg.type == 'human':
            user_query = normalize_content(msg.content)
            break
            
    if not user_query and messages:
        user_query = normalize_content(messages[1].content if len(messages) > 1 else messages[0].content)
    
    # 3. 序列化整个链路
    serialized_trace = []
    tool_names_set = set()
    total_input_tokens = 0
    total_output_tokens = 0
    
    for msg in messages:
        msg_type = msg.type
        msg_data = {
            "role": msg_type,
            "content": normalize_content(msg.content),
            "additional_kwargs": msg.additional_kwargs
        }
        
        if msg_type == 'ai' and hasattr(msg, 'tool_calls') and msg.tool_calls:
            msg_data["tool_calls"] = msg.tool_calls
            for tool_call in msg.tool_calls:
                tool_names_set.add(tool_call['name'])
        
        if msg_type == 'ai' and hasattr(msg, 'response_metadata'):
            usage = msg.response_metadata.get('token_usage', {})
            total_input_tokens += usage.get('input_tokens', 0)
            total_output_tokens += usage.get('output_tokens', 0)

        serialized_trace.append(msg_data)

    # 4. 提取最终回答
    final_answer = normalize_content(messages[-1].content) if messages and messages[-1].type == 'ai' else ""

    # 5. 计算执行耗时
    start_time = state.get("start_time")
    execution_duration = None
    if start_time is not None:
        execution_duration = time.time() - start_time

    # 6. 获取当前轮次号（从 state 中读取，由 log_agent_start 设置）
    turn_number = state.get('turn_number', 1)
    
    # 7. 异步创建记录（不阻塞主流程）
    async def save_trace():
        trace = AgentTrace(
            session_id=session_id,
            turn_number=turn_number,
            last_message_count=len(messages),
            user_query=user_query,
            query_embedding=None,
            full_trace=serialized_trace,
            final_answer=final_answer,
            tool_names=list(tool_names_set),
            token_usage={
                "input": total_input_tokens, 
                "output": total_output_tokens,
                "total": total_input_tokens + total_output_tokens
            },
            execution_duration=execution_duration,
            metadata_={
                "agent_runtime": str(runtime),
                "model": messages[-1].response_metadata.get('model_name') if messages and hasattr(messages[-1], 'response_metadata') else "unknown"
            },
            status=ResponseStatus.SUCCESS,
            fts_vector=None
        )
        try:
            save_agent_trace_to_pgvector(trace)
            print(f"✅ 链路已追加: Session={session_id[:8]}..., Turn={turn_number}, ID={trace.id}")
        except Exception as e:
            print(f"❌ 链路追加失败: {e}")
    
    # 异步执行，不等待结果
    asyncio.create_task(save_trace())


@wrap_tool_call
async def log_playwright_tool_call(
    request, handler
):
    """
    当前工具调用的中间件。如果工具是 MCP 浏览器工具，则截取当前页面的屏幕截图并将其保存到指定路径。
    该路径基于会话 ID、当前时间戳和工具调用 ID 进行命名，以确保唯一性。
    """
    tool_name = getattr(request.tool, 'name', '')
    if is_mcp_browser_tool(tool_name):
        response = await handler(request)
        print(f"Playwright Tool Called: {tool_name}")
        return response
    else:
        return await handler(request)