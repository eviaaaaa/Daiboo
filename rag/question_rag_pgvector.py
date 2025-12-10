from sqlalchemy.orm import Session
from typing import List
from entity import AgentTrace
from database import engine
from rag.hybrid_search_service import HybridSearchService

def get_question_from_pgvector(query: str, top_k: int = 3, use_rerank: bool = True) -> List[AgentTrace]:
    """
    根据查询文本，从 pgvector 向量库中检索相关 AgentTrace (混合检索)。
    
    Args:
        query (str): 查询文本
        top_k (int): 返回的相关文档数量，默认值为 3
        use_rerank (bool): 是否使用重排序
    
    Returns:
        list: 检索到的相关 AgentTrace 列表
    """
    with Session(engine) as session:
        service = HybridSearchService(session)
        results = service.search(AgentTrace, query, top_k=top_k, use_rerank=use_rerank)
        return results

def save_agent_trace_to_pgvector(trace: AgentTrace):
    """
    保存 AgentTrace 到数据库 (封装了 Session 管理)
    """
    try:
        with Session(engine) as session:
            session.add(trace)
            session.commit()
            print(f"Agent trace logged to database with ID: {trace.id}")
    except Exception as e:
        print(f"Failed to log agent trace to database: {e}")
        raise e