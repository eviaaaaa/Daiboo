"""
经验检索服务 - 专门用于从 Experience 表检索可复用的经验知识
与 AgentTrace（审计日志）检索分离
"""
from typing import List, Optional
from sqlalchemy.orm import Session

from entity.experience import Experience
from database import engine
from rag.hybrid_search_service import HybridSearchService


def search_experience(
    query: str, 
    task_type: Optional[str] = None,
    website_domain: Optional[str] = None,
    top_k: int = 3,
    use_rerank: bool = True
) -> List[Experience]:
    """
    根据查询检索相关经验
    
    参数：
        query: 查询文本
        task_type: 任务类型过滤（login/search/form/navigation/data_extraction/other）
        website_domain: 网站域名过滤（如 "github.com"）
        top_k: 返回的经验数量
        use_rerank: 是否使用重排序
    
    返回：
        相关经验列表
    """
    with Session(engine) as session:
        service = HybridSearchService(session)
        
        # 构建过滤条件
        filters = {}
        if task_type:
            filters['task_type'] = task_type
        if website_domain:
            filters['website_domain'] = website_domain
        
        # 执行混合检索
        results: List[Experience] = service.search(
            Experience, 
            query, 
            top_k=top_k, 
            use_rerank=use_rerank,
            **filters
        )
        
        # 清理返回数据（移除 embedding，节省 token）
        for exp in results:
            exp.experience_embedding = None
            exp.id = None
        
        return results


def format_experiences_for_prompt(experiences: List[Experience]) -> str:
    """
    将经验列表格式化为适合注入 Prompt 的文本
    
    参数：
        experiences: 经验列表
    
    返回：
        格式化的 Markdown 文本
    """
    if not experiences:
        return "未找到相关经验。"
    
    result_parts = ["以下是可能有帮助的经验：\n"]
    
    for i, exp in enumerate(experiences, 1):
        result_parts.append(f"## 经验 {i}：{exp.task_description}")
        result_parts.append(f"**任务类型**：{exp.task_type}")
        result_parts.append(f"**状态**：{'✅ 成功' if exp.success else '❌ 失败'}")
        
        if exp.website_domain:
            result_parts.append(f"**网站**：{exp.website_domain}")
        
        if exp.tool_names:
            result_parts.append(f"**使用工具**：{', '.join(exp.tool_names)}")
        
        result_parts.append(f"\n{exp.experience_content}\n")
        result_parts.append("---\n")
    
    return "\n".join(result_parts)


def get_experience_by_id(experience_id: int) -> Optional[Experience]:
    """
    根据 ID 获取单条经验（包含完整信息）
    
    参数：
        experience_id: 经验 ID
    
    返回：
        Experience 对象，不存在时返回 None
    """
    with Session(engine) as session:
        return session.get(Experience, experience_id)


def list_recent_experiences(limit: int = 10) -> List[Experience]:
    """
    列出最近的经验（用于调试或展示）
    
    参数：
        limit: 返回数量
    
    返回：
        经验列表
    """
    with Session(engine) as session:
        experiences = session.query(Experience).order_by(
            Experience.created_at.desc()
        ).limit(limit).all()
        
        # 清理 embedding
        for exp in experiences:
            exp.experience_embedding = None
        
        return experiences
