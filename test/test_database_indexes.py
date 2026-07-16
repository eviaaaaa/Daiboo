from contextlib import contextmanager
from types import SimpleNamespace


EXPECTED_INDEXES = {
    "ix_rag_documents_embedding_child_hnsw",
}


class FakeConnection:
    def __init__(self):
        self.statements = []

    def execute(self, statement):
        self.statements.append(str(statement))


class FakeEngine:
    def __init__(self):
        self.connection = FakeConnection()

    @contextmanager
    def begin(self):
        yield self.connection


def test_required_indexes_cover_vector_and_session_queries():
    from database.indexes import INDEX_STATEMENTS

    statements = "\n".join(INDEX_STATEMENTS)

    assert EXPECTED_INDEXES <= {
        statement.split("INDEX IF NOT EXISTS ", 1)[1].split()[0]
        for statement in INDEX_STATEMENTS
    }
    assert statements.count("USING hnsw") == 1
    assert statements.count("vector_cosine_ops") == 1
    assert "chunk_level = 'child'" in statements
    assert "agent_traces" not in statements
    assert "experiences" not in statements


def test_hybrid_vector_query_matches_partial_hnsw_predicate(monkeypatch):
    from sqlalchemy.dialects import postgresql

    from entity.rag_document import RagDocument
    from rag import hybrid_search_service as hybrid

    class ScalarRows:
        @staticmethod
        def all():
            return []

    class RecordingSession:
        def __init__(self):
            self.statements = []

        def scalars(self, statement):
            self.statements.append(statement)
            return ScalarRows()

    session = RecordingSession()
    monkeypatch.setattr(
        hybrid,
        "qwen_embeddings",
        SimpleNamespace(embed_query=lambda _query: [0.0] * 1536),
    )

    hybrid.HybridSearchService(session).search(
        RagDocument,
        "索引验证",
        top_k=3,
        use_rerank=False,
        chunk_level="child",
    )

    vector_sql = str(
        session.statements[0].compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )
    assert "embedding IS NOT NULL" in vector_sql
    assert "chunk_level = 'child'" in vector_sql


def test_ensure_database_indexes_is_idempotent_ddl(monkeypatch):
    from database import indexes

    engine = FakeEngine()
    create_all_calls = []
    monkeypatch.setattr(indexes.Base.metadata, "create_all", lambda bind: create_all_calls.append(bind))

    indexes.ensure_database_indexes(engine)
    indexes.ensure_database_indexes(engine)

    statements = engine.connection.statements
    assert create_all_calls == [engine.connection, engine.connection]
    assert all("IF NOT EXISTS" in statement for statement in statements)
    assert len(statements) == (len(indexes.INDEX_STATEMENTS) + 1) * 2
