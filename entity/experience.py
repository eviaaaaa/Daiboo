from datetime import datetime
from typing import List, Optional
from sqlalchemy import Integer, Text, String, Boolean, JSON, DateTime
from sqlalchemy.orm import Mapped, mapped_column
from pgvector.sqlalchemy import Vector
from .base import Base
from .mixins import SearchableMixin


class Experience(Base, SearchableMixin):
    """
    存储从 Agent 执行中提炼的经验知识，用于 RAG 检索。
    与 AgentTrace（审计日志）分离，专注于可复用的知识。
    """
    __tablename__ = "experiences"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True, init=False)

    # --- RAG 检索核心 ---
    
    # 任务类型分类 (用于结构化过滤)
    task_type: Mapped[str] = mapped_column(
        String(50), 
        nullable=False,
        comment="Task category: login, search, form, navigation, data_extraction, other"
    )
    
    # 任务描述 (用户原始意图)
    task_description: Mapped[str] = mapped_column(
        Text, 
        nullable=False,
        comment="Original user query or task intent"    
    )
    
    # 经验内容 (Markdown 格式)
    experience_content: Mapped[str] = mapped_column(
        Text, 
        nullable=False,
        comment="Structured experience in Markdown format"
    )
    
    # 经验向量 (用于语义检索)
    experience_embedding: Mapped[Optional[List[float]]] = mapped_column(
        Vector(1536), 
        nullable=True,
        comment="Embedding of experience_content for semantic search"
    )

    @property
    def search_content_field(self):
        """SearchableMixin 要求的属性：指定检索内容字段"""
        return self.experience_content

    @property
    def embedding_field(self):
        """SearchableMixin 要求的属性：指定向量字段"""
        return self.experience_embedding

    # --- 元数据与过滤 ---
    
    # 任务是否成功
    success: Mapped[bool] = mapped_column(
        Boolean, 
        default=True,
        comment="Whether the task was completed successfully"
    )
    
    # 使用的工具列表
    tool_names: Mapped[List[str]] = mapped_column(
        JSON, 
        default_factory=list,
        server_default='[]',
        comment="List of tools used in this task"
    )
    
    # 网站域名 (便于按网站过滤经验)
    website_domain: Mapped[Optional[str]] = mapped_column(
        String(200), 
        nullable=True,
        comment="Domain of the website (e.g., 'github.com')"
    )
    
    # --- 关联审计日志 (可选) ---
    
    # 关联的 AgentTrace ID (用于回溯完整链路)
    trace_id: Mapped[Optional[int]] = mapped_column(
        Integer, 
        nullable=True,
        comment="Reference to AgentTrace for audit purposes"
    )
    
    # 会话 ID (用于追踪同一会话产生的多条经验)
    session_id: Mapped[Optional[str]] = mapped_column(
        String(100), 
        nullable=True,
        index=True,
        comment="Session identifier for grouping experiences"
    )
    
    # 创建时间
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default_factory=datetime.utcnow,
        nullable=False
    )

    def __repr__(self):
        return f"<Experience(id={self.id}, type={self.task_type}, task='{self.task_description[:30]}...')>"
