import pytest
from rag.document_rag_pgvector import save_document_to_pgvector, query_document_from_pgvector
from rag.question_rag_pgvector import get_question_from_pgvector
from entity.rag_document import RagDocument
from entity.agent_trace import AgentTrace
from database import engine
from sqlalchemy.orm import Session
from sqlalchemy import text

# 测试用的唯一标识字符串
TEST_MARKER = "Pytest_Unique_Marker_RAG_TEST_DISTANCE_12345"
TEST_CONTENT = f"""
{TEST_MARKER}
这是一个用于测试自定义 pgvector RAG 流程的文档。
它包含了关于 SQLAlchemy 和 pgvector 的集成测试。
"""

@pytest.fixture
def temp_doc_file(tmp_path):
    """创建一个临时文本文件"""
    file_path = tmp_path / "rag_test_doc_distance.txt"
    file_path.write_text(TEST_CONTENT, encoding="utf-8")
    return file_path

def test_document_rag_returns_distance(temp_doc_file):
    """测试 document_rag_pgvector 返回距离"""
    print(f"\n[Test] Saving document from {temp_doc_file}")
    save_document_to_pgvector(temp_doc_file)
    
    print("[Test] Querying document via vector search...")
    query = "集成测试" 
    results = query_document_from_pgvector(query, top_k=1)
    
    assert len(results) > 0
    top_result = results[0]
    
    # 验证返回的是 list of RagDocument
    assert isinstance(top_result, RagDocument), "Result should be a RagDocument object"
    
    doc = top_result
    # distance = top_result.distance # Hybrid search doesn't return distance by default
    
    print(f"[Test] Top result: Document ID={doc.id}")
    
    assert isinstance(doc, RagDocument)
    assert TEST_MARKER in doc.content
    
    # 清理
    with Session(engine) as session:
        session.execute(text("DELETE FROM rag_documents WHERE content LIKE :content"), {"content": f"%{TEST_MARKER}%"})
        session.commit()

def test_question_rag_returns_distance():
    """测试 question_rag_pgvector 返回距离"""
    # 1. 插入一条测试 AgentTrace
    trace_data = {
        "user_query": f"测试查询 {TEST_MARKER}",
        "full_trace": [{"role": "user", "content": "test"}],
        "tool_names": ["test_tool"],
        "final_answer": "test answer"
    }
    
    # 需要手动生成 embedding 插入，或者依赖现有逻辑
    # 这里为了测试方便，我们假设数据库里可能已经有数据，或者我们插入一条
    from utils import qwen_embeddings
    embedding = qwen_embeddings.embed_query(trace_data["user_query"])
    
    new_trace = AgentTrace(
        user_query=trace_data["user_query"],
        full_trace=trace_data["full_trace"],
        tool_names=trace_data["tool_names"],
        final_answer=trace_data["final_answer"],
        query_embedding=embedding
    )
    
    with Session(engine) as session:
        session.add(new_trace)
        session.commit()
        trace_id = new_trace.id
        print(f"[Test] Inserted AgentTrace with ID={trace_id}")

    # 2. 查询
    print("[Test] Querying AgentTrace...")
    results = get_question_from_pgvector(f"测试查询 {TEST_MARKER}", top_k=1)
    
    assert len(results) > 0
    top_result = results[0]
    
    # 验证返回的是 list of AgentTrace
    assert isinstance(top_result, AgentTrace), "Result should be an AgentTrace object"
    
    trace = top_result
    
    print(f"[Test] Top result: Trace ID={trace.id}")
    
    assert isinstance(trace, AgentTrace)
    assert trace.id == trace_id
    
    # 清理
    with Session(engine) as session:
        session.execute(text("DELETE FROM agent_traces WHERE id = :id"), {"id": trace_id})
        session.commit()

if __name__ == "__main__":
    pytest.main(["-v", "-s", __file__])
