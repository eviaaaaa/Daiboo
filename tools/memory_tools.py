from langchain_core.tools import tool
from sqlalchemy.orm import Session
from sqlalchemy import select
from database.postgresql_database import engine
from entity.conversation_memory import ConversationRound

@tool
def read_archived_round(round_id: str):
    """
    根据 ID 读取已归档对话轮次的完整内容。
    当你在摘要中看到 [Ref: round_id] 并需要更多详细信息时使用此工具。
    """
    with Session(engine) as session:
        stmt = select(ConversationRound).where(ConversationRound.id == round_id)
        result = session.execute(stmt).scalar_one_or_none()
        if result:
            return result.full_content
        return f"未找到 ID 为 {round_id} 的轮次。"

@tool
def search_memory(query: str):
    """
    使用关键字搜索已归档的对话历史记录。
    返回相关轮次 ID 和片段的列表。
    """
    with Session(engine) as session:
        # 目前仅进行简单的关键字搜索
        stmt = select(ConversationRound).where(ConversationRound.full_content.ilike(f"%{query}%")).limit(5)
        results = session.execute(stmt).scalars().all()
        
        if not results:
            return "未找到匹配的记录。"
            
        output = ""
        for r in results:
            output += f"ID: {r.id}\n内容片段: {r.full_content[:200]}...\n\n"
        return output
