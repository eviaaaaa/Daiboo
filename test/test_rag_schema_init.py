import importlib


def test_ensure_rag_document_schema_reports_missing_schema_without_ddl(monkeypatch):
    module = importlib.import_module("rag.document_rag_pgvector")
    monkeypatch.setattr(module, "_schema_initialized", False, raising=False)

    calls = []

    class FakeMetadata:
        def create_all(self, engine):
            calls.append(("create_all", engine))

    class FakeSession:
        def __init__(self, engine):
            raise AssertionError("DDL session should not be opened")

    class FakeInspector:
        def get_columns(self, table_name):
            calls.append(("get_columns", table_name))
            return []

        def get_indexes(self, table_name):
            calls.append(("get_indexes", table_name))
            return []

    monkeypatch.setattr(module.RagDocument, "metadata", FakeMetadata())
    monkeypatch.setattr(module, "Session", FakeSession)
    monkeypatch.setattr(module, "engine", "fake-engine")
    monkeypatch.setattr(module, "inspect", lambda engine: FakeInspector())

    try:
        module.ensure_rag_document_schema()
    except RuntimeError as exc:
        assert "missing required columns" in str(exc)
    else:
        raise AssertionError("missing schema should be reported")

    assert calls == [
        ("create_all", "fake-engine"),
        ("get_columns", "rag_documents"),
        ("get_indexes", "rag_documents"),
    ]


def test_ensure_rag_document_schema_skips_ddl_when_schema_exists(monkeypatch):
    module = importlib.import_module("rag.document_rag_pgvector")
    monkeypatch.setattr(module, "_schema_initialized", False, raising=False)

    calls = []

    class FakeMetadata:
        def create_all(self, engine):
            calls.append(("create_all", engine))

    class FakeSession:
        def __init__(self, engine):
            raise AssertionError("DDL session should not be opened")

    class FakeInspector:
        def get_columns(self, table_name):
            calls.append(("get_columns", table_name))
            return [{"name": name} for name in module._SCHEMA_COLUMNS]

        def get_indexes(self, table_name):
            calls.append(("get_indexes", table_name))
            return [{"name": name} for name in module._SCHEMA_INDEXES]

    monkeypatch.setattr(module.RagDocument, "metadata", FakeMetadata())
    monkeypatch.setattr(module, "Session", FakeSession)
    monkeypatch.setattr(module, "engine", "fake-engine")
    monkeypatch.setattr(module, "inspect", lambda engine: FakeInspector())

    module.ensure_rag_document_schema()
    module.ensure_rag_document_schema()

    assert calls == [
        ("create_all", "fake-engine"),
        ("get_columns", "rag_documents"),
        ("get_indexes", "rag_documents"),
    ]


def test_inspection_engine_unwraps_lazy_engine(monkeypatch):
    module = importlib.import_module("rag.document_rag_pgvector")

    class FakeLazyEngine:
        def _engine(self):
            return "real-engine"

    monkeypatch.setattr(module, "engine", FakeLazyEngine())

    assert module._inspection_engine() == "real-engine"
