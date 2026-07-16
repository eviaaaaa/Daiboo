"""Idempotent PostgreSQL schema/index bootstrap for Daiboo's RAG tables."""
from __future__ import annotations

from sqlalchemy import text

from database import engine
from entity import AgentTrace, Experience  # noqa: F401 - register models with metadata
from entity.base import Base
from entity.rag_document import RagDocument  # noqa: F401 - register model


# Keep this list deliberately small: each index corresponds to a current hot
# query. The child-only HNSW predicate matches the production RAG retrieval
# filter and avoids indexing parent/legacy rows that are not searched there.
INDEX_STATEMENTS = (
    "CREATE INDEX IF NOT EXISTS ix_rag_documents_chunk_level ON rag_documents (chunk_level)",
    "CREATE INDEX IF NOT EXISTS ix_rag_documents_embedding_child_hnsw ON rag_documents USING hnsw (embedding vector_cosine_ops) WHERE embedding IS NOT NULL AND chunk_level = 'child'",
)


def _bind_engine(bind=None):
    if bind is not None:
        return bind
    return engine._engine() if hasattr(engine, "_engine") else engine


def ensure_database_indexes(bind=None) -> None:
    """Create required tables and indexes without failing on repeated startup."""
    db_engine = _bind_engine(bind)
    with db_engine.begin() as connection:
        connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        Base.metadata.create_all(bind=connection)
        for statement in INDEX_STATEMENTS:
            connection.execute(text(statement))
