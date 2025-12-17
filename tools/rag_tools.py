from langchain_core.tools import tool
from rag import document_rag_pgvector, question_rag_pgvector

@tool
def search_knowledge_base(query: str) -> str:
    """
    搜索知识库以获取相关文档和历史执行案例。
    当你需要外部知识、项目文档或类似任务的历史处理示例时，请使用此工具。
    
    Args:
        query: 搜索查询字符串。
    """
    try:
        # 1. 查询文档
        rag_docs = document_rag_pgvector.query_document_from_pgvector(query, top_k=3)
        
        # 2. 查询历史案例
        rag_exps = question_rag_pgvector.get_question_from_pgvector(query, top_k=3)

        # 3. 格式化输出
        docs_parts = []
        for i, doc in enumerate(rag_docs):
            docs_parts.append(f"文档片段 {i+1}:\n{doc.content}")
        
        docs_str = "\n\n".join(docs_parts)
        if not docs_str:
            docs_str = "未找到相关文档。"

        exps_str = ""
        for i, trace in enumerate(rag_exps):
            exps_str += f"历史案例 {i+1}:\n"
            exps_str += f"用户问题: {trace.user_query}\n"
            exps_str += f"执行过程: {str(trace.full_trace)}\n\n"
        
        if not exps_str:
            exps_str = "未找到相关历史案例。"

        return f"""
'{query}' 的搜索结果:

【相关文档】
{docs_str}

【相关历史案例】
{exps_str}
"""
    except Exception as e:
        return f"搜索知识库时出错: {str(e)}"
