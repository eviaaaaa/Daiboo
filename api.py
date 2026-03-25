import uvicorn
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from contextlib import asynccontextmanager
from langchain.messages import HumanMessage, AIMessage
from langgraph.types import Command
from typing import TYPE_CHECKING, Any, AsyncIterator, Optional
import json
import shutil
from pathlib import Path
import asyncio
import sys
import pprint
from utils.qwen_model import normalize_content

# 为 Playwright 设置 Windows 事件循环策略
if sys.platform == 'win32':
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

from utils.my_browser import ensure_browser_running
from utils.mcp_client import create_persistent_mcp_session
from utils.agent_factory import create_browser_agent, get_agent_tools
from rag.document_rag_pgvector import save_document_to_pgvector

if TYPE_CHECKING:
    from langchain_core.runnables import RunnableConfig
    from langgraph.graph.state import CompiledStateGraph
    try:
        from langgraph.types import StateSnapshot
    except ImportError:
        from langgraph.pregel.types import StateSnapshot

# 全局状态
class AppState:
    agent: "CompiledStateGraph"
    mcp_tools: Any | None = None  # 缓存工具列表，避免重复创建 subprocess

state = AppState()

# MCP 持久会话的 context manager 引用（需要手动管理生命周期）
_mcp_session_cm: Any | None = None
_mcp_session_cleanup: Any | None = None

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # 确保浏览器进程运行
    print("Ensuring browser is running...")
    await ensure_browser_running()

    # 使用持久 MCP 会话
    print("Starting persistent MCP session...")
    async with create_persistent_mcp_session() as mcp_tools:
        state.mcp_tools = mcp_tools

        # 创建 Agent
        print("Creating Agent...")
        state.agent = await create_browser_agent(mcp_tools)

        print("System initialized and ready.")
        yield

    # 退出 async with 后 MCP subprocess 自动清理
    print("MCP session cleaned up.")

app = FastAPI(
    lifespan=lifespan,
    title="NexusSurf API",
    description=(
        "提供浏览器自动化对话、可用工具查询和文档上传索引能力。"
        "其中 `/chat` 使用 NDJSON 流式返回执行过程与最终消息。"
    ),
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class ChatRequest(BaseModel):
    """聊天接口请求体。"""

    message: str = Field(..., description="用户输入的消息内容，或在中断恢复场景下提交的审批结果。")
    thread_id: str = Field("default", description="会话线程 ID，用于复用同一条 LangGraph 对话上下文。")


class ToolInfo(BaseModel):
    """工具信息。"""

    name: str = Field(..., description="工具名称。")
    description: str = Field(..., description="工具用途说明。")


class UploadResponse(BaseModel):
    """上传并索引文档后的响应体。"""

    status: str = Field(..., description="处理状态，成功时为 `success`。")
    filename: str = Field(..., description="上传文件名。")
    message: str = Field(..., description="处理结果说明。")


class ErrorResponse(BaseModel):
    """错误响应体。"""

    detail: str = Field(..., description="错误详情。")


@app.post(
    "/chat",
    summary="发送对话消息",
    description=(
        "向浏览器自动化 Agent 发送一条消息，并以 `application/x-ndjson` 流式返回执行日志、"
        "工具调用、中断通知和最终模型消息。"
    ),
    responses={
        200: {
            "description": "NDJSON 流式响应。每行都是一个 JSON 对象，`type` 可能为 `log`、`tool`、`message`、`interrupt` 或 `error`。",
            "content": {
                "application/x-ndjson": {
                    "example": (
                        '{"type":"log","content":"Resuming with approval..."}\n'
                        '{"type":"tool","content":"..."}\n'
                        '{"type":"message","content":"任务已完成"}\n'
                    )
                }
            },
        }
    },
    tags=["chat"],
)
async def chat(request: ChatRequest) -> StreamingResponse:
    """流式执行 Agent 对话。"""

    async def event_generator() -> AsyncIterator[str]:
        config: "RunnableConfig" = {"configurable": {"thread_id": request.thread_id}, "recursion_limit": 30}

        # 检查是否存在中断状态
        snapshot: "StateSnapshot" = await state.agent.aget_state(config)
        if snapshot.next:
            # 我们处于中断状态，将用户输入解释为决策
            user_input = request.message.strip().lower()
            if user_input in ["approve", "同意", "yes", "y"]:
                payload: dict[str, list[dict[str, str]]] = {"decisions": [{"type": "approve"}]}
                inputs: Command | dict[str, list[HumanMessage]] = Command(resume=payload)
                yield json.dumps({"type": "log", "content": "Resuming with approval..."}, ensure_ascii=False) + "\n"
            elif user_input in ["reject", "拒绝", "no", "n"]:
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
                    "log_agent_start.before_agent",
                    "log_experience.after_agent",
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
                            data = json.dumps({"type": "message", "content": normalize_content(msg.content)}, ensure_ascii=False)
                            yield f"{data}\n"
                            is_message = True

                if not is_message:
                    log_type = "log"
                    if "tools" in chunk:
                        log_type = "tool"

                    data = json.dumps({"type": log_type, "content": content}, ensure_ascii=False)
                    yield f"{data}\n"

            # 检查中断
            snapshot: "StateSnapshot" = await state.agent.aget_state(config)
            if snapshot.next:
                data = json.dumps({"type": "interrupt", "content": "Task interrupted. Approval needed."}, ensure_ascii=False)
                yield f"{data}\n"

        except Exception as e:
            data = json.dumps({"type": "error", "content": str(e)}, ensure_ascii=False)
            yield f"{data}\n"

    return StreamingResponse(event_generator(), media_type="application/x-ndjson")

@app.get(
    "/tools",
    summary="获取可用工具列表",
    description="返回当前 Agent 已加载的工具名称及说明，可用于前端展示或调试。",
    response_model=list[ToolInfo],
    tags=["tools"],
)
async def list_tools() -> list[dict[str, str]]:
    """列出当前可用的 Agent 工具。"""

    if not state.mcp_tools:
        return []
    # 直接使用缓存的工具列表，不再创建新 subprocess
    tools = get_agent_tools(state.mcp_tools)
    return [{"name": t.name, "description": t.description} for t in tools]

@app.post(
    "/upload",
    summary="上传文档并建立索引",
    description="上传单个文件到临时目录，并调用 PGVector 文档索引流程完成入库。",
    response_model=UploadResponse,
    responses={
        400: {"model": ErrorResponse, "description": "上传文件缺少文件名。"},
        500: {"model": ErrorResponse, "description": "文件保存或索引过程中发生异常。"},
    },
    tags=["documents"],
)
async def upload_document(
    file: UploadFile = File(..., description="待上传并建立索引的文件。")
) -> dict[str, str]:
    """上传文件并写入向量库。"""

    temp_dir: Path = Path("temp_uploads")
    temp_dir.mkdir(exist_ok=True)
    if not file.filename:
        raise HTTPException(status_code=400, detail="File name is required")
    file_path: Path = temp_dir / file.filename

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
