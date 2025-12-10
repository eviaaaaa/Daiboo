from typing import List, Dict, Any
from sqlalchemy import Integer, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from pgvector.sqlalchemy import Vector
from entity.base import Base
from entity.mixins import SearchableMixin

class RagDocument(Base, SearchableMixin):
    __tablename__ = "rag_documents"

    id: Mapped[int] = mapped_column(primary_key=True, init=False)

    # 所有字段都必须有默认值（因为 id 是 default，后面不能有 non-default）
    content: Mapped[str] = mapped_column(Text, default="")
    meta_data: Mapped[Dict[str, Any]] = mapped_column(JSONB, default_factory=dict)
    embedding: Mapped[List[float]] = mapped_column(Vector(1536), default_factory=list)

    @property
    def search_content_field(self):
        return self.content

    @property
    def embedding_field(self):
        return self.embedding