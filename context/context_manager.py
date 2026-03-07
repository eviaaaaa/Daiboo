import uuid
import os
import json
from typing import Any, Callable, Iterable, Optional

from langchain_core.messages import (
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
        session_id: str = "default_session",
        # 新增参数
        recent_tool_messages_to_keep: int = 1,  # 保留最近 N 条完整 ToolMessage
        tool_preview_chars: int = 200,          # ToolMessage 预览前后长度
        short_content_chars: int = 1000,        # 短内容阈值，低于此不压缩
        single_msg_max_chars: int = 120000,     # 单消息字符硬阈值
        max_total_chars: int = 200000,          # 总上下文字符硬阈值
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
            recent_tool_messages_to_keep: 保留最近 N 条完整 ToolMessage，默认 1
            tool_preview_chars: ToolMessage 预览前后长度，默认 200
            short_content_chars: 短内容阈值，低于此不压缩，默认 1000
            single_msg_max_chars: 单消息字符硬阈值，默认 120000
            max_total_chars: 总上下文字符硬阈值，默认 200000
        """
        self.file_store_path = file_store_path
        self.token_counter = token_counter
        self.session_id = session_id
        self.model = model

        # 新增配置参数
        self.recent_tool_messages_to_keep = recent_tool_messages_to_keep
        self.tool_preview_chars = tool_preview_chars
        self.short_content_chars = short_content_chars
        self.single_msg_max_chars = single_msg_max_chars
        self.max_total_chars = max_total_chars
        
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

        # 步骤 1: 单消息卸载 (字符硬阈值 OR token 阈值)
        processed_messages = self._offload_heavy_messages(messages)

        # 步骤 2: 压缩旧 ToolMessage (只保留最近 N 条)
        processed_messages = self._compress_old_tool_messages(processed_messages)

        # 步骤 3: 检查是否需要归档 (字符总量 OR token 总量超限)
        current_tokens = self.token_counter(processed_messages)
        total_chars = self._count_total_chars(processed_messages)

        if current_tokens < self.max_context_tokens and total_chars < self.max_total_chars:
            if processed_messages == messages:
                return None
            return {"messages": processed_messages}

        # 步骤 4: 归档旧的轮次
        final_messages = self._archive_old_rounds(processed_messages)

        return {
            "messages": [
                RemoveMessage(id=REMOVE_ALL_MESSAGES),
                *final_messages
            ]
        }

    def _count_total_chars(self, messages: list[AnyMessage]) -> int:
        """计算消息列表的总字符数"""
        total = 0
        for msg in messages:
            content = msg.content
            if isinstance(content, str):
                total += len(content)
            elif isinstance(content, list):
                for item in content:
                    if isinstance(item, dict) and "text" in item:
                        total += len(item["text"])
        return total

    def _ensure_message_ids(self, messages: list[AnyMessage]) -> None:
        for msg in messages:
            if msg.id is None:
                msg.id = str(uuid.uuid4())

    def _compress_old_tool_messages(self, messages: list[AnyMessage]) -> list[AnyMessage]:
        """
        压缩旧的 ToolMessage：只完整保留最近 N 条，其余长 ToolMessage 压缩为预览

        Args:
            messages: 消息列表

        Returns: 处理后的消息列表
        """
        # 找出所有 ToolMessage 的索引 (从后向前)
        tool_msg_indices = []
        for i, msg in enumerate(messages):
            if isinstance(msg, ToolMessage):
                tool_msg_indices.append(i)

        if not tool_msg_indices:
            return messages

        # 需要保留的最近 ToolMessage 数量
        keep_count = self.recent_tool_messages_to_keep

        # 如果 ToolMessage 数量 <= 保留数量，无需压缩
        if len(tool_msg_indices) <= keep_count:
            return messages

        # 需要压缩的 ToolMessage (从早到晚)
        indices_to_compress = tool_msg_indices[:-keep_count] if keep_count > 0 else tool_msg_indices

        new_messages = list(messages)
        for idx in indices_to_compress:
            msg = new_messages[idx]

            # 获取内容字符串
            content = msg.content
            if isinstance(content, list):
                # 处理多模态内容，转换为文本
                content_str = ""
                for item in content:
                    if isinstance(item, dict):
                        if item.get("type") == "text":
                            content_str += item.get("text", "")
                        elif item.get("type") == "image_url":
                            content_str += "[图片内容]"
            else:
                content_str = str(content)

            content_len = len(content_str)

            # 短内容不压缩
            if content_len <= self.short_content_chars:
                continue

            # 长内容压缩：保存到文件并替换为预览
            file_path = self._save_to_file(content_str, "toolmsg_content")
            preview = self._create_preview(content_str, self.tool_preview_chars)

            new_content = (
                f"[系统提示: 此 ToolMessage 内容过长 (共 {content_len} 字符)。\n"
                f"完整内容已保存至: {file_path}。\n"
                f"以下是内容预览:\n"
                f"--- BEGIN PREVIEW ---\n{preview}\n--- END PREVIEW ---\n"
                f"如果预览信息不足，请使用 terminal_read 工具读取完整文件。]"
            )

            # 创建新的 ToolMessage，保留必要字段
            new_messages[idx] = ToolMessage(
                content=new_content,
                tool_call_id=msg.tool_call_id,
                name=msg.name,
                id=msg.id,
                additional_kwargs=msg.additional_kwargs
            )
            print(f"⚠️ 旧 ToolMessage 已压缩: {content_len} 字符 -> {file_path}")

        return new_messages

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

                # 字符硬阈值 OR token 阈值，任一触发即卸载
                chars_exceeded = content_len > self.single_msg_max_chars
                tokens_exceeded = estimated_tokens > self.single_msg_limit

                if chars_exceeded or tokens_exceeded:
                    trigger = "字符" if chars_exceeded else "token"
                    file_path = self._save_to_file(content_str, "msg_content")
                    preview = self._create_preview(content_str, 500)

                    new_content = (
                        f"[系统提示: 此消息内容过长 (共 {content_len} 字符，估计 {estimated_tokens} tokens，触发条件: {trigger}超限)。\n"
                        f"完整内容已保存至: {file_path}。\n"
                        f"以下是内容预览:\n"
                        f"--- BEGIN PREVIEW ---\n{preview}\n--- END PREVIEW ---\n"
                        f"如果预览信息不足，请使用 terminal_read 工具读取完整文件。]"
                    )

                    # 创建带有新内容的副本
                    if isinstance(msg, HumanMessage):
                        msg_copy = HumanMessage(content=new_content, id=msg.id, additional_kwargs=msg.additional_kwargs)
                    elif isinstance(msg, ToolMessage):
                        msg_copy = ToolMessage(content=new_content, tool_call_id=msg.tool_call_id, name=msg.name, id=msg.id, additional_kwargs=msg.additional_kwargs)
                    else:
                        msg_copy = msg

                    new_messages.append(msg_copy)
                    print(f"⚠️ 消息过长已卸载 ({trigger}超限): {content_len} 字符 -> {file_path}")
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
            messages_to_keep = recent_messages.copy()
            
            notice_text = self._create_archive_notice_text(messages_to_archive, 
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
            messages_to_keep = messages_before + recent_messages.copy()
            
            notice_text = self._create_archive_notice_text(messages_to_archive,
                "历史对话已归档以优化上下文长度")
        
        # 将通知内容合并到第一个 HumanMessage 中，避免引入连续的 HumanMessage 导致抛出 400 角色不交替的错误
        for i, msg in enumerate(messages_to_keep):
            if isinstance(msg, HumanMessage):
                original_content = msg.content
                if isinstance(original_content, list):
                    new_content = [{"type": "text", "text": f"{notice_text}\n\n"}] + original_content
                else:
                    new_content = f"{notice_text}\n\n{original_content}"
                
                messages_to_keep[i] = HumanMessage(
                    content=new_content,
                    id=msg.id,
                    additional_kwargs=msg.additional_kwargs
                )
                break
        
        # 组装最终消息列表
        final_messages = system_msgs + messages_to_keep
        
        return final_messages
    
    def _create_archive_notice_text(self, messages_to_archive: list[AnyMessage], reason: str) -> str:
        """创建归档通知文本"""
        if not messages_to_archive:
            return f"[系统]: {reason}"
        
        # 将消息保存到文件
        round_data = ConversationRoundData(messages_to_archive)
        file_path = self._save_to_file(round_data.full_text, "archived_messages")
        preview = self._create_preview(round_data.full_text, 200)
        
        return (f"[系统]: {reason}\n\n"
                f"归档文件: {file_path}\n"
                f"预览:\n{preview}\n\n"
                "如需查看完整历史，请使用 terminal_read 工具读取归档文件。")

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

