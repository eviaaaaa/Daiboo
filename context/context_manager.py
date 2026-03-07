import uuid
import os
import json
from typing import Any, Callable, Iterable, cast, Optional
from datetime import datetime

from langchain_core.messages import (
    AIMessage,
    AnyMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
    RemoveMessage,
    MessageLikeRepresentation
)
from langchain_core.messages.utils import count_tokens_approximately
from langchain_core.language_models.chat_models import BaseChatModel
from langgraph.graph.message import REMOVE_ALL_MESSAGES
from langgraph.runtime import Runtime

# Try to import AgentMiddleware, if not available, define a protocol or base class
try:
    from langchain.agents.middleware.types import AgentMiddleware, AgentState
except ImportError:
    class AgentMiddleware:
        def before_model(self, state: Any, runtime: Any) -> dict[str, Any] | None:
            pass
    AgentState = dict[str, Any]

# from sqlalchemy.orm import Session
# from database.postgresql_database import engine
# from entity.conversation_memory import ConversationRound

TokenCounter = Callable[[Iterable[MessageLikeRepresentation]], int]

class ConversationRoundData:
    def __init__(self, messages: list[AnyMessage]):
        self.messages = messages
        
    @property
    def full_text(self) -> str:
        # 将消息序列化为文本以进行存储/显示
        text = ""
        for msg in self.messages:
            role = msg.type
            content = msg.content
            text += f"{role}: {content}\n"
        return text
    
    def to_json(self) -> str:
        # 将消息序列化为 JSON
        return json.dumps([m.dict() for m in self.messages], default=str, ensure_ascii=False)

class ContextManagerMiddleware(AgentMiddleware):
    def __init__(
        self,
        model: Optional[BaseChatModel] = None,
        file_store_path: str = os.getenv("HEAVY_MESSAGES_DIR", os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "storage", "heavy_messages")),
        max_token_ratio: float = 0.8,    # 使用模型 max_input_tokens 的 80%
        single_msg_ratio: float = 0.8,   # 单条消息限制为 max_input_tokens 的 80%
        token_counter: TokenCounter = count_tokens_approximately,
        session_id: str = "default_session"
    ):
        """
        初始化 Context Manager Middleware
        
        Args:
            model: LangChain 模型实例，用于读取 max_input_tokens
            file_store_path: 消息存储路径
            max_token_ratio: 总 token 限制比例，默认 0.8
            single_msg_ratio: 单条消息 token 限制比例，默认 0.8
            token_counter: Token 计数函数
            session_id: 会话 ID
        """
        self.file_store_path = file_store_path
        self.token_counter = token_counter
        self.session_id = session_id
        self.model = model
        
        # 从模型的 profile 中读取 max_input_tokens
        if model and hasattr(model, 'profile') and isinstance(model.profile, dict):
            max_input_tokens = model.profile.get('max_input_tokens', 128000)
        else:
            # 默认值
            max_input_tokens = 128000
        
        # 根据倍率计算实际限制
        self.max_context_tokens = int(max_input_tokens * max_token_ratio)
        self.single_msg_limit = int(max_input_tokens * single_msg_ratio)
        
        if not os.path.exists(self.file_store_path):
            os.makedirs(self.file_store_path)

    def _save_to_file(self, content: str, prefix: str) -> str:
        """将内容保存到文件并返回路径"""
        file_name = f"{prefix}_{uuid.uuid4()}.txt"
        file_path = os.path.join(self.file_store_path, file_name)
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(content)
        return file_path

    def _create_preview(self, content: str, preview_len: int = 500) -> str:
        """生成内容预览"""
        if len(content) <= preview_len * 2:
            return content
        head = content[:preview_len]
        tail = content[-preview_len:]
        return f"{head}\n... [省略 {len(content) - preview_len * 2} 字符] ...\n{tail}"

    def before_model(self, state: AgentState, runtime: Runtime) -> dict[str, Any] | None:
        messages = state["messages"]
        self._ensure_message_ids(messages)
        
        # 步骤 1: 卸载过大的消息
        processed_messages = self._offload_heavy_messages(messages)
        
        # 步骤 2: 检查是否需要归档
        current_tokens = self.token_counter(processed_messages)
        if current_tokens < self.max_context_tokens:
            if processed_messages == messages:
                return None
            return {"messages": processed_messages}
            
        # 步骤 3: 归档旧的轮次
        final_messages = self._archive_old_rounds(processed_messages)
        
        return {
            "messages": [
                RemoveMessage(id=REMOVE_ALL_MESSAGES),
                *final_messages
            ]
        }

    def _ensure_message_ids(self, messages: list[AnyMessage]) -> None:
        for msg in messages:
            if msg.id is None:
                msg.id = str(uuid.uuid4())

    def _offload_heavy_messages(self, messages: list[AnyMessage]) -> list[AnyMessage]:
        new_messages = []
        for msg in messages:
            if isinstance(msg, (HumanMessage, ToolMessage)):
                # 检查内容长度
                content_str = str(msg.content)
                content_len = len(content_str)
                
                # 使用字符长度估算（1 token ≈ 4 chars for Chinese, ≈ 1 char for English）
                # 取平均值：1 token ≈ 2 chars
                estimated_tokens = content_len // 2
                
                # 如果估算超过限制，直接卸载，避免精确计数（太耗时）
                if estimated_tokens > self.single_msg_limit:
                    file_path = self._save_to_file(content_str, "msg_content")
                    preview = self._create_preview(content_str, 500)

                    new_content = (
                        f"[系统提示: 此消息内容过长 (共 {content_len} 字符，估计 {estimated_tokens} tokens)。\n"
                        f"完整内容已保存至: {file_path}。\n"
                        f"以下是内容预览:\n"
                        f"--- BEGIN PREVIEW ---\n{preview}\n--- END PREVIEW ---\n"
                        f"如果预览信息不足，请使用 terminal_read 工具读取完整文件。]"
                    )
                    
                    # 创建带有新内容的副本
                    if isinstance(msg, HumanMessage):
                        msg_copy = HumanMessage(content=new_content, id=msg.id, additional_kwargs=msg.additional_kwargs)
                    elif isinstance(msg, ToolMessage):
                        msg_copy = ToolMessage(content=new_content, tool_call_id=msg.tool_call_id, id=msg.id, additional_kwargs=msg.additional_kwargs)
                    else:
                        msg_copy = msg
                        
                    new_messages.append(msg_copy)
                    print(f"⚠️ 消息过长已卸载: {content_len} 字符 -> {file_path}")
                    continue
            
            new_messages.append(msg)
        return new_messages

    def _archive_old_rounds(self, messages: list[AnyMessage]) -> list[AnyMessage]:
        """
        新的压缩策略：
        1. 先计算最后一条 HumanMessage 及其之后的所有消息的 token 数
        2. 如果超出限制：压缩除最后一条消息外的所有消息（不包括 SystemMessage）
        3. 如果没超出限制：压缩从第一个 HumanMessage 到最后一个 HumanMessage 前一条消息
        """
        system_msgs = [m for m in messages if isinstance(m, SystemMessage)]
        chat_history = [m for m in messages if not isinstance(m, SystemMessage)]
        
        if not chat_history:
            return messages
        
        # 计算 SystemMessage 的 token 数
        system_tokens = self.token_counter(system_msgs)
        
        # 找到最后一条 HumanMessage 的位置
        last_human_idx = -1
        for i in range(len(chat_history) - 1, -1, -1):
            if isinstance(chat_history[i], HumanMessage):
                last_human_idx = i
                break
        
        if last_human_idx == -1:
            # 没有 HumanMessage，不需要压缩
            return messages
        
        # 计算最后一条 HumanMessage 及其之后的所有消息的 token 数
        recent_messages = chat_history[last_human_idx:]
        recent_tokens = self.token_counter(recent_messages) + system_tokens
        
        # 策略 1: 如果最近的消息已经超出限制，压缩除最后一条外的所有消息
        if recent_tokens > self.max_context_tokens:
            if last_human_idx == 0:
                # 只有一条 HumanMessage，无法压缩
                return messages
            
            messages_to_archive = chat_history[:last_human_idx]
            messages_to_keep = recent_messages
            
            archive_notice = self._create_archive_notice(messages_to_archive, 
                "最近的对话内容较长，已归档旧消息以节省空间")
        else:
            # 策略 2: 压缩从第一个 HumanMessage 到最后一个 HumanMessage 前一条消息
            
            # 找到第一条 HumanMessage
            first_human_idx = -1
            for i, msg in enumerate(chat_history):
                if isinstance(msg, HumanMessage):
                    first_human_idx = i
                    break
            
            if first_human_idx == -1 or first_human_idx >= last_human_idx:
                # 没有需要压缩的消息
                return messages
            
            # 压缩第一条到最后一条前一条之间的消息
            messages_to_archive = chat_history[first_human_idx:last_human_idx]
            messages_before = chat_history[:first_human_idx]  # 第一条 HumanMessage 之前的消息
            messages_to_keep = messages_before + recent_messages
            
            archive_notice = self._create_archive_notice(messages_to_archive,
                "历史对话已归档以优化上下文长度")
        
        # 组装最终消息列表
        final_messages = system_msgs + [archive_notice] + messages_to_keep
        
        return final_messages
    
    def _create_archive_notice(self, messages_to_archive: list[AnyMessage], reason: str) -> HumanMessage:
        """创建归档通知消息"""
        if not messages_to_archive:
            return HumanMessage(content=f"[系统]: {reason}")
        
        # 将消息保存到文件
        round_data = ConversationRoundData(messages_to_archive)
        file_path = self._save_to_file(round_data.full_text, "archived_messages")
        preview = self._create_preview(round_data.full_text, 200)
        
        archive_notice = HumanMessage(
            content=f"[系统]: {reason}\n\n"
                    f"归档文件: {file_path}\n"
                    f"预览:\n{preview}\n\n"
                    "如需查看完整历史，请使用 terminal_read 工具读取归档文件。"
        )
        
        return archive_notice

    def _archive_and_summarize(self, rounds_to_archive: list[ConversationRoundData]) -> str:
        archived_items = []
        
        for i, round_data in enumerate(rounds_to_archive):
            # 保存到文件系统
            file_path = self._save_to_file(round_data.full_text, "round_archive")
            
            archived_items.append({
                "file_path": file_path,
                "content": round_data.full_text
            })

        # 生成摘要 (不再使用 LLM，仅列出文件)
        summary_text = "以下轮次已归档:\n"
        for item in archived_items:
            # 简单的预览
            preview = self._create_preview(item['content'], 200)
            summary_text += f"\n--- 归档文件: {item['file_path']} ---\n预览:\n{preview}\n"

        return summary_text

