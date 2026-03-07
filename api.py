import uvicorn
from fastapi import FastAPI, UploadFile, File, HTTPException, Body
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from contextlib import asynccontextmanager
from playwright.async_api import async_playwright
from langchain.messages import HumanMessage, AIMessage
from langgraph.types import Command
import json
import os
import shutil
from pathlib import Path
import asyncio
import sys
import pprint

# 为 Playwright 设置 Windows 事件循环策略
if sys.platform == 'win32':
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

from utils.my_browser import launch_or_connect_browser
from agent_factory import create_browser_agent, get_agent_tools
from rag.document_rag_pgvector import save_document_to_pgvector

# 全局状态
class AppState:
    browser = None
    agent = None
    playwright = None

state = AppState()

@asynccontextmanager
async def lifespan(app: FastAPI):
    # 初始化 Playwright
    print("Initializing Playwright...")
    state.playwright = await async_playwright().start()
    
    # 初始化浏览器
    print("Connecting to Browser...")
    # 当使用异步 playwright 时，launch_or_connect_browser 返回一个协程
    state.browser = await launch_or_connect_browser(state.playwright)
    
    # 确保至少存在一个上下文和页面
    print("Ensuring browser context and page...")
    contexts = state.browser.contexts
    if not contexts:
        context = await state.browser.new_context()
    else:
        context = contexts[0]
        
    if not context.pages:
        await context.new_page()
    
    # 初始化智能体
    print("Creating Agent...")
    state.agent = create_browser_agent(state.browser)
    
    print("System initialized and ready.")
    yield
    
    # 清理资源
    print("Cleaning up...")
    if state.browser:
        await state.browser.close()
    if state.playwright:
        await state.playwright.stop()

app = FastAPI(lifespan=lifespan, title="NexusSurf API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class ChatRequest(BaseModel):
    message: str
    thread_id: str = "default"


@app.post("/chat")
async def chat(request: ChatRequest):
    async def event_generator():
        config = {"configurable": {"thread_id": request.thread_id}, "recursion_limit": 80}
        
        # 检查是否存在中断状态
        snapshot = await state.agent.aget_state(config)
        if snapshot.next:
            # 我们处于中断状态，将用户输入解释为决策
            user_input = request.message.strip().lower()
            if user_input in ["approve", "同意", "yes", "y"]:
                payload = {"decisions": [{"type": "approve"}]}
                inputs = Command(resume=payload)
                yield json.dumps({"type": "log", "content": "Resuming with approval..."}, ensure_ascii=False) + "\n"
            elif user_input in ["reject", "拒绝", "no", "n"]:
                # 简单的拒绝，可以解析原因
                payload = {"decisions": [{"type": "reject", "message": "User rejected."}]}
                inputs = Command(resume=payload)
                yield json.dumps({"type": "log", "content": "Resuming with rejection..."}, ensure_ascii=False) + "\n"
            else:
                payload = {"decisions": [{"type": "reject", "message": request.message}]}
                inputs = Command(resume=payload)
                yield json.dumps({"type": "log", "content": f"Resuming with rejection (reason: {request.message})..."}, ensure_ascii=False) + "\n"
        else:
            # 正常聊天流程
            inputs = {"messages": [HumanMessage(content=f"用户问题：{request.message}")]}
        
        try:
            async for chunk in state.agent.astream(inputs, config=config, stream_mode="updates"):
                # 过滤掉不必要的中间件日志
                keys = list(chunk.keys())
                if len(keys) == 1 and keys[0] in [
                    "ContextManagerMiddleware.before_model",
                    "HumanInTheLoopMiddleware.after_model",
                    "log_response_to_database.after_agent",
                    "log_agent_response.after_agent",
                    "log_agent_start.before_agent"
                ]:
                    continue

                # 分析数据块以区分日志和实际消息
                is_message = False
                content = pprint.pformat(chunk)
                
                # 检查是否是带有 AIMessage 的模型响应
                if "model" in chunk and "messages" in chunk["model"]:
                    messages = chunk["model"]["messages"]
                    for msg in messages:
                        if isinstance(msg, AIMessage):
                            # 找到智能体的响应
                            data = json.dumps({"type": "message", "content": msg.content}, ensure_ascii=False)
                            yield f"{data}\n"
                            is_message = True
                
                if not is_message:
                    # 确定日志类型以便更好的前端显示
                    log_type = "log"
                    if "tools" in chunk:
                        log_type = "tool"
                    
                    # 以日志形式发送
                    data = json.dumps({"type": log_type, "content": content}, ensure_ascii=False)
                    yield f"{data}\n"
                
            # 检查中断
            snapshot = await state.agent.aget_state(config)
            if snapshot.next:
                data = json.dumps({"type": "interrupt", "content": "Task interrupted. Approval needed."}, ensure_ascii=False)
                yield f"{data}\n"
                
        except Exception as e:
            data = json.dumps({"type": "error", "content": str(e)}, ensure_ascii=False)
            yield f"{data}\n"

    return StreamingResponse(event_generator(), media_type="application/x-ndjson")

@app.get("/tools")
async def list_tools():
    if not state.browser:
        return []
    tools = get_agent_tools(state.browser)
    return [{"name": t.name, "description": t.description} for t in tools]

@app.post("/upload")
async def upload_document(file: UploadFile = File(...)):
    temp_dir = Path("temp_uploads")
    temp_dir.mkdir(exist_ok=True)
    file_path = temp_dir / file.filename
    
    try:
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
            
        # 调用 RAG 保存函数
        await asyncio.to_thread(save_document_to_pgvector, [file_path])
        
        return {"status": "success", "filename": file.filename, "message": "Document indexed successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8801)
