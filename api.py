import uvicorn
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from contextlib import asynccontextmanager
from pathlib import Path
from langchain.messages import HumanMessage, AIMessage
from langgraph.types import Command
from langgraph.checkpoint.sqlite import SqliteSaver
from typing import TYPE_CHECKING, Any, AsyncIterator, Optional
import json
import shutil
import os
from pathlib import Path
import asyncio
import sys
import pprint
from dotenv import load_dotenv
from loguru import logger
from utils.auth import AuthMiddleware
from utils.config import app_host, app_port, project_env_file
from utils.logging import setup_logging
from utils.qwen_model import normalize_content

load_dotenv(dotenv_path=project_env_file())
setup_logging()

# 为 Playwright 设置 Windows 事件循环策略
if sys.platform == 'win32':
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

from utils.my_browser import ensure_browser_running
from utils.mcp_client import create_persistent_mcp_session
from utils.agent_factory import create_browser_agent, get_agent_tools
from utils.upload_paths import build_safe_upload_path
from utils.config import upload_dir
from utils.skills import get_skill_by_name, load_skills
from rag.document_rag_pgvector import (
    debug_query_document_from_pgvector,
    get_rag_corpus_summary,
    save_document_to_pgvector,
)

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
    logger.info("Ensuring browser is running...")
    await ensure_browser_running()

    # 使用持久 MCP 会话
    logger.info("Starting persistent MCP session...")
    async with create_persistent_mcp_session() as mcp_tools:
        state.mcp_tools = mcp_tools

        # SQLite checkpointer：会话跨重启持久化
        db_dir = Path(os.getenv("DAIBOO_CHECKPOINT_DIR", str(Path(__file__).resolve().parent / "data")))
        db_dir.mkdir(parents=True, exist_ok=True)
        db_path = str(db_dir / "agent_checkpoints.db")
        logger.info("Opening checkpoint DB: {}", db_path)

        with SqliteSaver.from_conn_string(db_path) as checkpointer:
            # 创建 Agent
            logger.info("Creating Agent...")
            state.agent = await create_browser_agent(mcp_tools, checkpointer=checkpointer)

            logger.info("System initialized and ready.")
            yield

    # 退出 async with 后 MCP subprocess 自动清理
    logger.info("MCP session cleaned up.")

app = FastAPI(
    lifespan=lifespan,
    title="Daiboo API",
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

# 认证 + 限流（DAIBOO_API_KEY 未设时自动关闭）
app.add_middleware(AuthMiddleware)

# HTTP 请求日志中间件
@app.middleware("http")
async def log_requests(request, call_next):
    resp = await call_next(request)
    logger.bind(
        method=request.method,
        path=request.url.path,
        status_code=resp.status_code,
    ).info("request")
    return resp

FRONTEND_DIR = Path(__file__).resolve().parent / "frontend"
app.mount(
    "/vendor",
    StaticFiles(directory=FRONTEND_DIR / "vendor"),
    name="frontend-vendor",
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
    total_parents: int = Field(0, description="本次索引生成的大块数量。")
    total_children: int = Field(0, description="本次索引生成的小块数量。")


class RagSearchRequest(BaseModel):
    """RAG 调试检索请求体。"""

    query: str = Field(..., min_length=1, description="用户输入的检索问题。")
    top_k: int = Field(5, ge=1, le=10, description="每种策略返回的结果数量。")
    use_rerank: bool = Field(True, description="是否开启重排序。")


class ChunkConfig(BaseModel):
    parent_size: int
    parent_overlap: int
    child_size: int
    child_overlap: int


class RagChunkResult(BaseModel):
    id: Optional[int] = None
    content: str
    source_name: Optional[str] = None
    source_path: Optional[str] = None
    chunk_level: Optional[str] = None
    chunk_index: Optional[int] = None
    parent_id: Optional[int] = None
    start_index: Optional[int] = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    content_preview: str
    content_length: int


class HierarchicalRagResult(BaseModel):
    parent: RagChunkResult
    matched_children: list[RagChunkResult]


class RagSearchStrategies(BaseModel):
    large_chunks: list[RagChunkResult]
    small_chunks: list[RagChunkResult]
    hierarchical: list[HierarchicalRagResult]


class RagSearchResponse(BaseModel):
    query: str
    top_k: int
    use_rerank: bool
    legacy_fallback_used: bool = False
    chunk_config: ChunkConfig
    strategies: RagSearchStrategies


class RagCorpusSource(BaseModel):
    source_name: str
    source_path: Optional[str] = None
    parent_chunks: int
    child_chunks: int
    total_rows: int


class RagCorpusSummaryResponse(BaseModel):
    total_parent_chunks: int
    total_child_chunks: int
    total_legacy_rows: int
    sources: list[RagCorpusSource]


class ErrorResponse(BaseModel):
    """错误响应体。"""

    detail: str = Field(..., description="错误详情。")


class HealthResponse(BaseModel):
    """健康检查响应体。"""

    status: str = Field(..., description="服务状态，正常时为 ok。")
    tools_loaded: bool = Field(..., description="MCP 工具是否已加载。")
    agent_ready: bool = Field(..., description="Agent 是否已编译就绪。")


@app.get("/", include_in_schema=False)
async def frontend_index() -> FileResponse:
    return FileResponse(FRONTEND_DIR / "index.html")


@app.get(
    "/health",
    summary="健康检查",
    description="返回服务健康状态，包括 MCP 工具加载状态和 Agent 就绪状态。",
    response_model=HealthResponse,
    tags=["system"],
)
async def health_check() -> dict[str, Any]:
    """健康检查：MCP 工具 + Agent 是否就绪。"""
    return {
        "status": "ok",
        "tools_loaded": state.mcp_tools is not None,
        "agent_ready": hasattr(state, "agent") and state.agent is not None,
    }


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
            logger.exception("Chat streaming error for thread {}", request.thread_id)
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


class SkillSummary(BaseModel):
    """技能概要信息。"""

    name: str = Field(..., description="技能名称。")
    description: str = Field(..., description="技能用途说明。")
    version: str = Field("0.0.0", description="技能版本号。")
    path: str = Field("", description="技能目录本地路径。")
    tags: list[str] | None = Field(None, description="技能标签列表。")


class SkillDetail(SkillSummary):
    """技能详情。"""

    content: str = Field(..., description="技能完整 Markdown 正文。")


@app.get(
    "/skills",
    summary="获取可用技能列表",
    description="返回当前已加载的所有技能名称、描述和版本信息。",
    response_model=list[SkillSummary],
    tags=["skills"],
)
async def list_skills_endpoint() -> list[dict[str, Any]]:
    """列出所有可用的 Skills。"""
    skills = load_skills()
    return [
        {
            "name": s.name,
            "description": s.description,
            "version": s.version,
            "tags": s.tags,
        }
        for s in skills
    ]


@app.get(
    "/skills/{name}",
    summary="获取技能详情",
    description="返回指定技能的完整内容，包括 frontmatter 元数据和 Markdown 正文。",
    response_model=SkillDetail,
    responses={404: {"model": ErrorResponse, "description": "未找到该技能。"}},
    tags=["skills"],
)
async def view_skill_endpoint(name: str) -> dict[str, Any]:
    """加载并返回技能完整内容。"""
    skill = get_skill_by_name(name)
    if skill is None:
        raise HTTPException(status_code=404, detail=f"Skill '{name}' not found")
    return {
        "name": skill.name,
        "description": skill.description,
        "version": skill.version,
        "tags": skill.tags,
        "content": skill.content,
    }


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
) -> dict[str, Any]:
    """上传文件并写入向量库。"""

    temp_dir: Path = upload_dir()
    temp_dir.mkdir(parents=True, exist_ok=True)

    try:
        display_name, file_path = build_safe_upload_path(temp_dir, file.filename or "")
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        # 调用 RAG 保存函数
        indexing_summary = await asyncio.to_thread(save_document_to_pgvector, [file_path])

        return {
            "status": "success",
            "filename": display_name,
            "message": "Document indexed successfully",
            "total_parents": indexing_summary["total_parents"],
            "total_children": indexing_summary["total_children"],
        }
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as e:
        logger.exception("Document upload/indexing failed for {}", file.filename or "unknown")
        raise HTTPException(status_code=500, detail=str(e))


@app.post(
    "/rag/search",
    summary="调试 RAG 检索效果",
    description="同时返回大块检索、小块检索和层级聚合结果，便于前端对比大小块效果并查看相关 chunk。",
    response_model=RagSearchResponse,
    tags=["documents"],
)
async def debug_rag_search(request: RagSearchRequest) -> dict[str, Any]:
    """返回 RAG 调试检索结果。"""

    try:
        return await asyncio.to_thread(
            debug_query_document_from_pgvector,
            request.query,
            request.top_k,
            request.use_rerank,
        )
    except Exception as exc:
        logger.exception("RAG search failed for query: {}", request.query[:100])
        raise HTTPException(status_code=500, detail=str(exc))


@app.get(
    "/rag/summary",
    summary="获取 RAG 语料概览",
    description="返回当前索引库中的文档、父子块数量和旧数据数量，便于前端展示当前可测试范围。",
    response_model=RagCorpusSummaryResponse,
    tags=["documents"],
)
async def rag_corpus_summary() -> dict[str, Any]:
    try:
        return await asyncio.to_thread(get_rag_corpus_summary)
    except Exception as exc:
        logger.exception("RAG corpus summary failed")
        raise HTTPException(status_code=500, detail=str(exc))

if __name__ == "__main__":
    uvicorn.run(app, host=app_host(), port=app_port())
