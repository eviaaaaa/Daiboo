# models.py
import enum
from datetime import datetime
from typing import Dict, Any, Optional, List
from sqlalchemy import (
    Integer,
    Text,
    JSON,
    DateTime,
    String,
    Float
)
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.ext.hybrid import hybrid_property
from pgvector.sqlalchemy import Vector
from .base import Base
from .mixins import SearchableMixin

class ResponseStatus(enum.Enum):
    SUCCESS = "success"
    FAILURE = "failure"

class AgentTrace(Base, SearchableMixin):
    """
    存储 Agent 的完整执行链路，用于 RAG 检索“最佳实践”或“历史记忆”。
    """
    __tablename__ = "agent_traces"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True, init=False)

    # --- 检索核心 ---
    
    # 用户原始输入 (用于语义检索：寻找相似的任务)
    # 例如："1024杯水...然后登录网站..."
    user_query: Mapped[str] = mapped_column(Text, nullable=False)

    @property
    def search_content_field(self):
        return self.user_query

    @property
    def embedding_field(self):
        return self.query_embedding

    # 完整对话链路 (JSON 格式)
    # 包含：[HumanMessage, AIMessage(CoT), ToolMessage(Result), AIMessage(Final)]
    # 这是 RAG 最有价值的部分，可以作为 Few-Shot Example 注入到 Prompt 中
    full_trace: Mapped[List[Dict[str, Any]]] = mapped_column(
        JSON,
        nullable=False,
        comment="Serialized LangChain messages list"
    )
    
    # 向量字段 (建议使用 text-embedding-3-small 或 text-embedding-3-large)
    # 对 user_query 进行 embedding
    query_embedding: Mapped[Optional[list[float]]] = mapped_column(
        Vector(1536), 
        nullable=True,
        default=None,
        comment="Embedding of the user_query"
    )
    
    # 别名，用于统一接口 (HybridSearchService 默认使用 .embedding)
    @hybrid_property
    def embedding(self):
        return self.query_embedding

    # --- 知识核心 (RAG 的 Payload) ---

    # 最终的文本回答 (仅作为快速预览或摘要)
    final_answer: Mapped[str] = mapped_column(Text, nullable=True, default=None)

    # --- 过滤与优化 ---

    # 本次任务使用过的工具列表 (用于结构化过滤)
    # 例如：["navigate_browser", "fill_text", "click_element"]
    tool_names: Mapped[List[str]] = mapped_column(
        JSON, 
        default_factory=list,
        server_default='[]',
        comment="List of tool names used in this trace"
    )

    # 任务执行状态
    status: Mapped[ResponseStatus] = mapped_column(
        String,
        nullable=False,
        default=ResponseStatus.SUCCESS.value
    )

    # 执行总耗时 (秒)，RAG 时可以优先检索执行快的案例
    execution_duration: Mapped[Optional[float]] = mapped_column(Float, nullable=True, default=None)

    # Token 消耗详情 (input, output, total)
    token_usage: Mapped[Dict[str, int]] = mapped_column(
        JSON,
        default_factory=dict,
        server_default='{}'
    )

    # 元数据 (Session ID, User ID, Model Name 等)
    metadata_: Mapped[Dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
        default_factory=dict,
        server_default="{}"
    )

    # --- 会话管理 (用于多轮对话去重) ---
    
    # 会话 ID (用于追踪同一对话窗口)
    session_id: Mapped[Optional[str]] = mapped_column(
        String(100),
        nullable=True,
        index=True,
        comment="Session identifier for grouping conversation rounds"
    )
    
    # 对话轮次 (同一 session 内递增)
    turn_number: Mapped[int] = mapped_column(
        Integer,
        default=1,
        server_default='1',
        comment="Turn number within the session"
    )
    
    # 已记录的消息数 (用于计算增量)
    last_message_count: Mapped[int] = mapped_column(
        Integer,
        default=0,
        server_default='0',
        comment="Number of messages recorded in this trace"
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default_factory=datetime.utcnow,
        nullable=False
    )

    def __repr__(self):
        return f"<AgentTrace(id={self.id}, query='{self.user_query[:30]}...', tools={self.tool_names})>"