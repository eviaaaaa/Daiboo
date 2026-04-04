from langchain_core.documents import Document

from rag.document_chunking import (
    CHILD_CHUNK_SIZE,
    PARENT_CHUNK_SIZE,
    build_parent_child_chunks,
    rank_parent_results,
)


def test_build_parent_child_chunks_creates_hierarchy():
    long_text = "这是用于测试大小块切分的内容。" * 400
    docs = [Document(page_content=long_text, metadata={"source": "demo.txt"})]

    structured_chunks = build_parent_child_chunks(docs)

    assert structured_chunks, "should produce parent chunks"
    assert len(structured_chunks) > 1, "long text should be split into multiple parent chunks"

    for parent_index, chunk in enumerate(structured_chunks):
        parent_doc = chunk["parent_doc"]
        children = chunk["children"]

        assert parent_doc.metadata["chunk_level"] == "parent"
        assert parent_doc.metadata["chunk_index"] == parent_index
        assert len(parent_doc.page_content) <= PARENT_CHUNK_SIZE + PARENT_CHUNK_SIZE // 5

        assert children, "each parent chunk should produce at least one child chunk"
        for child_index, child_doc in enumerate(children):
            assert child_doc.metadata["chunk_level"] == "child"
            assert child_doc.metadata["chunk_index"] == child_index
            assert child_doc.metadata["parent_chunk_index"] == parent_index
            assert len(child_doc.page_content) <= CHILD_CHUNK_SIZE + CHILD_CHUNK_SIZE // 5


def test_rank_parent_results_aggregates_multiple_child_hits():
    child_results = [
        type("StubDoc", (), {"id": 11, "parent_id": 101})(),
        type("StubDoc", (), {"id": 12, "parent_id": 202})(),
        type("StubDoc", (), {"id": 13, "parent_id": 101})(),
        type("StubDoc", (), {"id": 14, "parent_id": 303})(),
    ]

    ranked_parent_ids = rank_parent_results(child_results, top_k=3)

    assert ranked_parent_ids[0] == 101
    assert ranked_parent_ids == [101, 202, 303]


def test_rank_parent_results_falls_back_to_self_id_for_legacy_rows():
    child_results = [
        type("StubDoc", (), {"id": 5, "parent_id": None})(),
        type("StubDoc", (), {"id": 7, "parent_id": None})(),
    ]

    ranked_parent_ids = rank_parent_results(child_results, top_k=2)

    assert ranked_parent_ids == [5, 7]
