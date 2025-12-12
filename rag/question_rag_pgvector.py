from sqlalchemy.orm import Session
from typing import List, Dict, Any
from entity import AgentTrace
from database import engine
from rag.hybrid_search_service import HybridSearchService

def simplify_trace_content(messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    简化 LangChain 消息列表，移除过长的工具输出和图片数据。
    """
    if not messages:
        return []
        
    simplified_messages = []
    for msg in messages:
        # 复制消息字典，避免修改原始引用
        new_msg = msg.copy()
        msg_type = new_msg.get("type")
        content = new_msg.get("content")

        # 1. 简化 ToolMessage：工具返回的 DOM 通常巨大且无用
        if msg_type == "tool":
            if isinstance(content, str) and len(content) > 200:
                # 保留前200字符，让 LLM 知道工具是成功了还是报错了
                new_msg["content"] = content[:200] + "... [Output Truncated for RAG]"
            elif not isinstance(content, str):
                new_msg["content"] = "[Complex Tool Output Omitted]"

        # 2. 简化包含图片的 Human/AI 消息 (多模态内容)
        # LangChain 序列化后的 content 可能是 list[dict]
        if isinstance(content, list):
            new_content = []
            for item in content:
                if isinstance(item, dict):
                    # 只保留文本部分
                    if item.get("type") == "text":
                        new_content.append(item)
                    elif item.get("type") == "image_url":
                        # 替换图片为占位符
                        new_content.append({"type": "text", "text": "[Image Omitted]"})
                elif isinstance(item, str):
                    new_content.append(item)
            new_msg["content"] = new_content

        simplified_messages.append(new_msg)
    return simplified_messages

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
        results: List[AgentTrace] = service.search(AgentTrace, query, top_k=top_k, use_rerank=use_rerank)
    for trace in results:
        trace.id = None  # 不返回ID，节省token
        trace.query_embedding = None  # 不返回向量，节省token
        trace.fts_vector = None  # 不返回全文检索索引(非对话链路)，节省token
        trace.created_at = None
        trace.token_usage = None
        trace.metadata_ = None
        trace.execution_duration = None
        trace.final_answer = None
        
        # 深度简化 full_trace 内容
        if trace.full_trace:
            trace.full_trace = simplify_trace_content(trace.full_trace)
            
    return results

def save_agent_trace_to_pgvector(trace: AgentTrace):
    """
    保存 AgentTrace 到数据库 (封装了 Session 管理)
    会自动清洗 full_trace 中的 RAG Context，防止 Token 膨胀。
    """
    # --- 核心清洗逻辑：去重影 (De-Contextualize) ---
    # 1. 尝试从 user_query 中提取纯净的 query
    #    假设 Prompt 模板总是 "Context...\n\n用户问题：{query}" 这种格式
    if trace.user_query:
        # 简单的启发式清洗：如果 user_query 包含 "用户问题：" 标记，则截取后面的部分
        split_marker = "用户问题："
        if split_marker in trace.user_query:
            clean_query = trace.user_query.split(split_marker)[-1].strip()
            trace.user_query = clean_query
            print(f"🧹 已清洗 user_query: {clean_query[:50]}...")

    # 2. 清洗 full_trace 中的第一条 HumanMessage
    if trace.full_trace and trace.user_query:
        # 遍历消息列表，找到第一条 HumanMessage
        for msg in trace.full_trace:
            # 兼容不同的序列化格式 (dict 或 object)
            msg_type = msg.get("type") if isinstance(msg, dict) else getattr(msg, "type", "")
            
            if msg_type in ["human", "user"]:
                # 强制将其内容重置为清洗后的 user_query
                # 这样就剥离了之前注入的 "这是可能有帮助的相关文档..." 等 RAG 上下文
                if isinstance(msg, dict):
                    msg["content"] = trace.user_query
                else:
                    msg.content = trace.user_query
                
                # 只需处理第一条 HumanMessage，后续的对话是正常的
                break
    # ---------------------------------------------

    try:
        with Session(engine) as session:
            session.add(trace)
            session.commit()
            print(f"Agent trace logged to database with ID: {trace.id}")
    except Exception as e:
        print(f"Failed to log agent trace to database: {e}")
        raise e