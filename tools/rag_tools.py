from langchain_core.tools import tool
from rag import document_rag_pgvector
from rag.experience_rag import search_experience, format_experiences_for_prompt


@tool
def search_documents(query: str) -> str:
    """
    搜索项目文档和技术文档。
    当你需要查找API文档、技术说明、配置信息、项目知识时使用此工具。
    
    Args:
        query: 搜索查询字符串。
    
    Returns:
        相关文档内容的格式化字符串。
    """
    try:
        docs = document_rag_pgvector.query_document_from_pgvector(query, top_k=3)
        
        if not docs:
            return "未找到相关文档。"
        
        docs_parts = []
        for i, doc in enumerate(docs, 1):
            docs_parts.append(f"### 文档片段 {i}\n{doc.content}")
        
        return f"查询 '{query}' 的文档结果:\n\n" + "\n\n".join(docs_parts)
    
    except Exception as e:
        return f"搜索文档时出错: {str(e)}"


@tool
def search_task_experience(
    query: str,
    task_type: str = None,
    website: str = None
) -> str:
    """
    搜索历史任务执行经验。
    当你需要了解如何完成类似任务、如何使用特定工具、如何处理类似场景时使用此工具。
    
    Args:
        query: 任务描述或问题，例如 "如何登录网站" "如何填写表单" "如何提取数据"
        task_type: 可选，任务类型过滤。可选值: login/search/form/navigation/data_extraction/other
        website: 可选，网站域名过滤，例如 "github.com" "baidu.com"
    
    Returns:
        相关经验的格式化字符串，包含任务描述、使用的工具、执行步骤等。
    """
    try:
        experiences = search_experience(
            query=query,
            task_type=task_type,
            website_domain=website,
            top_k=3,
            use_rerank=True
        )
        
        formatted = format_experiences_for_prompt(experiences)
        return f"查询 '{query}' 的经验结果:\n\n{formatted}"
    
    except Exception as e:
        return f"搜索经验时出错: {str(e)}"
