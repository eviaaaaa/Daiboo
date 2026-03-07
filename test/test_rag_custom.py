import pytest
from rag.document_rag_pgvector import save_document_to_pgvector, query_document_from_pgvector
from entity.rag_document import RagDocument
from database import engine
from sqlalchemy.orm import Session
from sqlalchemy import text

# 测试用的唯一标识字符串，方便清理
TEST_MARKER = "Pytest_Unique_Marker_RAG_TEST_12345"
TEST_CONTENT = f"""
{TEST_MARKER}
这是一个用于测试自定义 pgvector RAG 流程的文档。
它包含了关于 SQLAlchemy 和 pgvector 的集成测试。
"""

@pytest.fixture
def temp_doc_file(tmp_path):
    """创建一个临时文本文件"""
    file_path = tmp_path / "rag_test_doc.txt"
    file_path.write_text(TEST_CONTENT, encoding="utf-8")
    return file_path

def test_save_and_query_rag(temp_doc_file):
    """测试保存和查询流程"""
    
    print(f"\n[Test] Saving document from {temp_doc_file}")
    
    # 1. 保存文档
    # 这会自动创建表和扩展（如果不存在）
    save_document_to_pgvector(temp_doc_file)
    
    # 2. 验证数据库中是否有数据 (直接 SQL 验证)
    with Session(engine) as session:
        stmt = text("SELECT count(*) FROM rag_documents WHERE content LIKE :content")
        count = session.execute(stmt, {"content": f"%{TEST_MARKER}%"}).scalar()
        assert count > 0, "Database should contain the inserted document content"
        print(f"[Test] Found {count} records in database matching marker.")

    # 3. 向量查询
    print("[Test] Querying document via vector search...")
    query = "集成测试" 
    results = query_document_from_pgvector(query, top_k=1)
    
    # 4. 验证查询结果
    assert len(results) > 0, "Should return at least one result"
    top_doc = results[0]
    
    print(f"[Test] Top result content: {top_doc.content[:50]}...")
    
    assert isinstance(top_doc, RagDocument)
    assert TEST_MARKER in top_doc.content, "The retrieved document should contain the test marker"
    
    # 5. 清理数据
    print("[Test] Cleaning up test data...")
    with Session(engine) as session:
        session.execute(text("DELETE FROM rag_documents WHERE content LIKE :content"), {"content": f"%{TEST_MARKER}%"})
        session.commit()
    print("[Test] Cleanup complete.")

if __name__ == "__main__":
    # 允许直接运行
    pytest.main(["-v", "-s", __file__])
