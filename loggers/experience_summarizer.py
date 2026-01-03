"""
经验总结器 - 异步分析 Agent 执行链路并生成可复用的经验知识
"""
import json
import re
from typing import Optional
from sqlalchemy.orm import Session
from langchain_core.messages import HumanMessage

from entity.experience import Experience
from database import engine
from utils import qwen_embeddings, create_qwen_model
from prompt.experience_prompt import EXPERIENCE_SUMMARY_PROMPT, format_trace_for_summary


class ExperienceSummarizer:
    """
    经验总结器 - 负责从 AgentTrace 中提炼经验并保存到 Experience 表
    """
    
    def __init__(self):
        self.llm = create_qwen_model(temperature=0.1)
        self.embeddings = qwen_embeddings
    
    async def summarize_from_state(self, state: dict) -> Optional[int]:
        """
        从 graph 的 state 中提取信息并异步总结经验（便捷方法）
        不依赖数据库查询，直接从 state 解析所有需要的数据，实现真正的异步并行
        
        Args:
            state: LangGraph 的 state 对象
        
        Returns:
            成功时返回 Experience ID，失败或跳过时返回 None
        """
        try:
            # 1. 从 state 获取 session_id
            session_id = state.get('configurable', {}).get('thread_id')
            messages = state.get('messages', [])
            if not session_id and messages:
                session_id = messages[0].id
            
            if not session_id:
                print("⚠️ 无法从 state 中获取 session_id")
                return None
            
            # 2. 从 state 获取 turn_number
            turn_number = state.get('turn_number', 1)
            
            # 3. 从 messages 中解析所有需要的数据
            if not messages:
                print("⚠️ State 中没有 messages")
                return None
            
            # 提取 user_query（最后一条 HumanMessage）
            user_query = ""
            for msg in reversed(messages):
                if msg.type == 'human':
                    user_query = msg.content
                    break
            
            if not user_query and len(messages) > 1:
                user_query = messages[1].content if len(messages) > 1 else messages[0].content
            
            # 序列化 full_trace 并提取 tool_names
            serialized_trace = []
            tool_names_set = set()
            print(f"📝 正在序列化执行记录 (Session: {session_id[:8]}..., Turn: {turn_number})")
            for msg in messages:
                msg_type = msg.type
                msg_data = {
                    "role": msg_type,
                    "content": msg.content,
                    "additional_kwargs": msg.additional_kwargs
                }
                
                if msg_type == 'ai' and hasattr(msg, 'tool_calls') and msg.tool_calls:
                    msg_data["tool_calls"] = msg.tool_calls
                    for tool_call in msg.tool_calls:
                        tool_names_set.add(tool_call['name'])
                
                serialized_trace.append(msg_data)
            
            # 提取 final_answer
            final_answer = messages[-1].content if messages and messages[-1].type == 'ai' else ""
            
            # 4. 格式化执行记录
            trace_summary = format_trace_for_summary(serialized_trace)
            print(f"📝 格式化执行记录摘要 (Session: {session_id[:8]}..., Turn: {turn_number})")
            # 5. 构建 Prompt
            prompt = EXPERIENCE_SUMMARY_PROMPT.format(
                user_query=user_query,
                tool_names=", ".join(tool_names_set) if tool_names_set else "无",
                final_answer=final_answer or "无",
                trace_summary=trace_summary
            )
            
            # 6. 调用 LLM 生成总结
            print(f"🤔 开始分析 (Session: {session_id[:8]}..., Turn: {turn_number})...")
            response = await self.llm.ainvoke([HumanMessage(content=prompt)])
            
            # 7. 解析 JSON 结果
            result = self._parse_llm_response(response.content)
            print(result)
            if not result:
                print(f"⚠️ 无法解析 LLM 响应")
                return None
            
            # 8. 判断是否值得记录
            if not result.get('is_valuable', False):
                print(f"⏭️ 不值得记录为经验 (Session: {session_id[:8]}..., Turn: {turn_number})")
                return None
            
            # 9. 生成 Embedding
            experience_text = result.get('experience', '')
            if not experience_text:
                print(f"⚠️ 经验内容为空")
                return None
            
            embedding = self.embeddings.embed_documents([experience_text])[0]
            
            # 10. 创建 Experience 对象并保存
            with Session(engine) as db_session:
                experience = Experience(
                    task_type=result.get('task_type', 'other'),
                    task_description=user_query,
                    experience_content=experience_text,
                    experience_embedding=embedding,
                    success=result.get('success', True),
                    tool_names=list(tool_names_set),
                    website_domain=result.get('website_domain'),
                    trace_id=None,  # 不依赖 trace_id，因为是异步并行
                    session_id=session_id
                )
                
                db_session.add(experience)
                db_session.commit()
                
                print(f"✨ 经验已记录: ID={experience.id}, 类型={experience.task_type}")
                return experience.id
                
        except Exception as e:
            session_id_str = session_id[:8] if 'session_id' in locals() else 'unknown'
            turn_num = turn_number if 'turn_number' in locals() else '?'
            print(f"⚠️ 经验总结失败 (Session: {session_id_str}..., Turn: {turn_num}): {e}")
            import traceback
            traceback.print_exc()
            return None
    
    def _parse_llm_response(self, response_text: str) -> Optional[dict]:
        """
        解析 LLM 返回的 JSON 响应
        
        Args:
            response_text: LLM 的原始响应
        
        Returns:
            解析后的字典，失败时返回 None
        """
        try:
            # 尝试直接解析
            return json.loads(response_text)
        except json.JSONDecodeError:
            # 尝试提取 JSON 代码块
            json_match = re.search(r'```json\s*(\{.*?\})\s*```', response_text, re.DOTALL)
            if json_match:
                try:
                    return json.loads(json_match.group(1))
                except json.JSONDecodeError:
                    pass
            
            # 尝试提取纯 JSON（不在代码块中）
            json_match = re.search(r'\{.*\}', response_text, re.DOTALL)
            if json_match:
                try:
                    return json.loads(json_match.group(0))
                except json.JSONDecodeError:
                    pass
            
            print(f"⚠️ 无法解析响应: {response_text[:200]}...")
            return None
