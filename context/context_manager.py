import uuid
import os
import json
from typing import Any, Callable, Iterable, cast
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
from langgraph.graph.message import REMOVE_ALL_MESSAGES
from langgraph.runtime import Runtime
from langchain.chat_models import BaseChatModel, init_chat_model

# Try to import AgentMiddleware, if not available, define a protocol or base class
try:
    from langchain.agents.middleware.types import AgentMiddleware, AgentState
except ImportError:
    class AgentMiddleware:
        def before_model(self, state: Any, runtime: Any) -> dict[str, Any] | None:
            pass
    AgentState = dict[str, Any]

from sqlalchemy.orm import Session
from database.postgresql_database import engine
from entity.conversation_memory import ConversationRound

TokenCounter = Callable[[Iterable[MessageLikeRepresentation]], int]

SUMMARY_PROMPT = """
你是对话历史管理员。你的任务是将旧的对话轮次压缩成摘要，但必须保留对原始记录的引用 ID。

以下是需要归档的对话片段，每个片段都有一个 ID：
{content}

要求：
1. 将这些对话合并成一段连贯的叙述性摘要。
2. **必须**在摘要的相关位置标注 `[Ref: ID]`。
3. 如果多个轮次讨论同一个主题，可以合并，但要列出所有涉及的 ID。

示例输出：
用户首先询问了 Docker 的配置 [Ref: round_123]，随后遇到网络报错，AI 建议修改 bridge 模式 [Ref: round_124]。最后用户确认问题解决 [Ref: round_125]。
"""

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
        model: str | BaseChatModel,
        file_store_path: str = r"c:\my\python\langchain\BrowerController\storage\heavy_messages",
        max_context_tokens: int = 12000, # 根据需要调整
        single_msg_limit: int = 4000,    # 根据需要调整
        token_counter: TokenCounter = count_tokens_approximately,
        session_id: str = "default_session"
    ):
        if isinstance(model, str):
            model = init_chat_model(model)
            
        self.model = model
        self.file_store_path = file_store_path
        self.max_context_tokens = max_context_tokens
        self.single_msg_limit = single_msg_limit
        self.token_counter = token_counter
        self.session_id = session_id
        
        if not os.path.exists(self.file_store_path):
            os.makedirs(self.file_store_path)

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
                # 检查 token 数量或长度
                if len(str(msg.content)) > self.single_msg_limit * 4: # 先进行粗略的字符计数检查
                     if self.token_counter([msg]) > self.single_msg_limit:
                        file_name = f"msg_content_{uuid.uuid4()}.txt"
                        file_path = os.path.join(self.file_store_path, file_name)
                        
                        with open(file_path, "w", encoding="utf-8") as f:
                            f.write(str(msg.content))
                        
                        new_content = (
                            f"[系统提示: 此消息内容过长。"
                            f"已保存至: {file_path}。"
                            f"如果需要，请使用 terminal_read 工具读取。]"
                        )
                        
                        # 创建带有新内容的副本
                        # 注意: msg.copy() 可能因版本不同而不按预期工作，使用构造函数
                        if isinstance(msg, HumanMessage):
                            msg_copy = HumanMessage(content=new_content, id=msg.id, additional_kwargs=msg.additional_kwargs)
                        elif isinstance(msg, ToolMessage):
                            msg_copy = ToolMessage(content=new_content, tool_call_id=msg.tool_call_id, id=msg.id, additional_kwargs=msg.additional_kwargs)
                        else:
                            msg_copy = msg # 鉴于 if 检查，这种情况不应发生
                            
                        new_messages.append(msg_copy)
                        continue
            
            new_messages.append(msg)
        return new_messages

    def _archive_old_rounds(self, messages: list[AnyMessage]) -> list[AnyMessage]:
        system_msgs = [m for m in messages if isinstance(m, SystemMessage)]
        chat_history = [m for m in messages if not isinstance(m, SystemMessage)]
        
        rounds = []
        current_round = []
        
        for msg in chat_history:
            if isinstance(msg, HumanMessage) and current_round:
                rounds.append(ConversationRoundData(current_round))
                current_round = []
            current_round.append(msg)
        
        if current_round:
            rounds.append(ConversationRoundData(current_round))
            
        if len(rounds) <= 1:
            return messages
            
        # 归档除最后 2 轮之外的所有内容（当前活跃轮次 + 上一轮上下文）
        rounds_to_archive = rounds[:-2]
        rounds_to_keep = rounds[-2:]
        
        if not rounds_to_archive:
             return messages

        # 归档并生成摘要
        summary_text = self._archive_and_summarize(rounds_to_archive)
        
        archive_notice = HumanMessage(
            content=f"[系统]: 较旧的对话历史已归档。摘要如下：\n{summary_text}\n"
                    "如果需要之前主题的上下文，请使用带有 Ref ID 的 'search_memory' 或 'read_archived_round' 工具。"
        )
        
        final_messages = system_msgs + [archive_notice]
        for r in rounds_to_keep:
            final_messages.extend(r.messages)
            
        return final_messages

    def _archive_and_summarize(self, rounds_to_archive: list[ConversationRoundData]) -> str:
        archived_items = []
        
        with Session(engine) as session:
            for i, round_data in enumerate(rounds_to_archive):
                # 保存到数据库
                db_round = ConversationRound(
                    session_id=self.session_id,
                    round_index=i, # 此索引逻辑可能需要改进为全局索引，但目前相对索引也可以，或者我们可以查询最大值
                    full_content=round_data.to_json(),
                    tags=[]
                )
                session.add(db_round)
                session.flush() # 生成 ID
                
                archived_items.append({
                    "id": db_round.id,
                    "content": round_data.full_text
                })
            session.commit()

        # 生成摘要
        summary_input = ""
        for item in archived_items:
            summary_input += f"\n--- Round ID: {item['id']} ---\n{item['content']}\n"

        try:
            response = self.model.invoke(SUMMARY_PROMPT.format(content=summary_input))
            summary_text = cast(str, response.content).strip()
            
            # 更新数据库中的摘要（可选，但有利于后续的向量搜索）
            # 我们需要解析摘要以找到哪个 ID 对应哪段文本，
            # 或者直接存储所有这些轮次的整个摘要块。
            # 目前，我们只是将文本返回给上下文。
            
            return summary_text
        except Exception as e:
            return f"生成摘要时出错: {e}"

