"""
测试 Context Manager 压缩策略

覆盖范围：
- 旧 ToolMessage 压缩 (只保留最近 1 条完整)
- 单消息 token 阈值
- tool_call_id / name 保留
- 总上下文 token 阈值触发归档
"""
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier

# 添加项目根目录到 Python 路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from langchain_core.messages import (
    HumanMessage, AIMessage, SystemMessage, ToolMessage, RemoveMessage,
)
from langchain_core.messages.utils import count_tokens_approximately
from context.context_manager import ContextManagerMiddleware


# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------

def _make_middleware(**overrides) -> ContextManagerMiddleware:
    """创建用于测试的中间件，使用临时目录和小阈值便于触发"""
    test_store = project_root / "storage"
    test_store.mkdir(exist_ok=True)
    defaults = dict(
        model=None,
        file_store_path=str(test_store),
        max_token_ratio=0.8,
        single_msg_ratio=0.8,
        token_counter=count_tokens_approximately,
        recent_tool_messages_to_keep=1,
        tool_preview_chars=200,
        short_content_chars=1000,
    )
    defaults.update(overrides)
    return ContextManagerMiddleware(**defaults)


class _ModelWithContext:
    """最小模型桩，只提供 ContextManagerMiddleware 需要的 profile。"""

    def __init__(self, max_input_tokens: int = 100):
        self.profile = {"max_input_tokens": max_input_tokens}


def _count_content_chars(messages) -> int:
    """测试用 token_counter: 1 字符按 1 token 计，便于精确触发阈值。"""
    return sum(len(str(getattr(msg, "content", ""))) for msg in messages)


def _count_ten_tokens_per_message(messages) -> int:
    """测试用 token_counter: 每条消息固定 10 token。"""
    return len(list(messages)) * 10


def _long_text(n: int) -> str:
    """生成 n 个字符的填充文本"""
    base = "abcdefghij"  # 10 个字符
    return (base * (n // 10 + 1))[:n]


def _run(mw: ContextManagerMiddleware, messages: list) -> list | None:
    """运行 before_model 并返回处理后的消息列表（去除 RemoveMessage）"""
    result = mw.before_model({"messages": messages}, None)
    if result is None:
        return None
    return [m for m in result["messages"] if not isinstance(m, RemoveMessage)]


# ---------------------------------------------------------------------------
# 测试 1: 旧 ToolMessage 压缩
# ---------------------------------------------------------------------------

def test_old_tool_messages_compressed_recent_kept():
    """多条 ToolMessage 时，最近 1 条完整保留，其余长 ToolMessage 被压缩"""
    mw = _make_middleware(short_content_chars=100)
    long_content = _long_text(2000)  # 远超 short_content_chars

    messages = [
        SystemMessage(content="system"),
        HumanMessage(content="q1", id="h1"),
        AIMessage(content="a1", id="a1", tool_calls=[{"id": "tc1", "name": "tool_a", "args": {}}]),
        ToolMessage(content=long_content, tool_call_id="tc1", name="tool_a", id="t1"),
        AIMessage(content="a2", id="a2", tool_calls=[{"id": "tc2", "name": "tool_b", "args": {}}]),
        ToolMessage(content=long_content, tool_call_id="tc2", name="tool_b", id="t2"),
        AIMessage(content="a3", id="a3", tool_calls=[{"id": "tc3", "name": "tool_c", "args": {}}]),
        ToolMessage(content=long_content, tool_call_id="tc3", name="tool_c", id="t3"),  # 最近的
        AIMessage(content="final", id="a4"),
        HumanMessage(content="q2", id="h2"),
    ]

    result = _run(mw, messages)
    assert result is not None, "应返回处理结果"

    tool_msgs = [m for m in result if isinstance(m, ToolMessage)]
    assert len(tool_msgs) == 3, "ToolMessage 数量不变"

    # 最近的 (t3) 应保持完整
    t3 = next(m for m in tool_msgs if m.id == "t3")
    assert t3.content == long_content, "最近 1 条 ToolMessage 应完整保留"

    # 旧的 (t1, t2) 应被压缩
    for tid in ("t1", "t2"):
        tm = next(m for m in tool_msgs if m.id == tid)
        assert "已保存至" in tm.content, f"{tid} 应包含文件路径"
        assert "BEGIN PREVIEW" in tm.content, f"{tid} 应包含预览"
        assert len(tm.content) < len(long_content), f"{tid} 压缩后应更短"

    print("PASS: test_old_tool_messages_compressed_recent_kept")


def test_short_tool_messages_not_compressed():
    """短 ToolMessage 即使不是最近的也不压缩"""
    mw = _make_middleware(short_content_chars=1000)

    messages = [
        SystemMessage(content="system"),
        HumanMessage(content="q1", id="h1"),
        AIMessage(content="a1", id="a1", tool_calls=[{"id": "tc1", "name": "tool_a", "args": {}}]),
        ToolMessage(content="short result", tool_call_id="tc1", name="tool_a", id="t1"),  # 短
        AIMessage(content="a2", id="a2", tool_calls=[{"id": "tc2", "name": "tool_b", "args": {}}]),
        ToolMessage(content="another short", tool_call_id="tc2", name="tool_b", id="t2"),  # 最近
        HumanMessage(content="q2", id="h2"),
    ]

    result = _run(mw, messages)
    # 短消息不应被压缩，且总量不超限，可能返回 None
    if result is None:
        # 没有任何修改，符合预期
        print("PASS: test_short_tool_messages_not_compressed (no changes)")
        return

    tool_msgs = [m for m in result if isinstance(m, ToolMessage)]
    for tm in tool_msgs:
        assert "已保存至" not in tm.content, f"{tm.id} 不应被压缩"

    print("PASS: test_short_tool_messages_not_compressed")


def test_tool_call_id_and_name_preserved():
    """压缩后 tool_call_id 和 name 必须保留"""
    mw = _make_middleware(short_content_chars=100)
    long_content = _long_text(2000)

    messages = [
        SystemMessage(content="system"),
        HumanMessage(content="q1", id="h1"),
        AIMessage(content="a1", id="a1", tool_calls=[{"id": "tc_old", "name": "get_elements", "args": {}}]),
        ToolMessage(content=long_content, tool_call_id="tc_old", name="get_elements", id="t_old"),
        AIMessage(content="a2", id="a2", tool_calls=[{"id": "tc_new", "name": "click", "args": {}}]),
        ToolMessage(content="ok", tool_call_id="tc_new", name="click", id="t_new"),
        HumanMessage(content="q2", id="h2"),
    ]

    result = _run(mw, messages)
    assert result is not None

    t_old = next(m for m in result if isinstance(m, ToolMessage) and m.id == "t_old")
    assert t_old.tool_call_id == "tc_old", "tool_call_id 应保留"
    assert t_old.name == "get_elements", "name 应保留"

    print("PASS: test_tool_call_id_and_name_preserved")


# ---------------------------------------------------------------------------
# 测试 2: 单消息 token 阈值
# ---------------------------------------------------------------------------

def test_single_msg_token_limit_triggers_offload():
    """单条消息 token 超限时应触发卸载"""
    mw = _make_middleware(
        model=_ModelWithContext(max_input_tokens=10000),
        max_token_ratio=1.0,      # 上下文预算 10000 tokens，避免后续归档干扰
        single_msg_ratio=0.0025,  # 单消息预算 25 tokens
        token_counter=_count_content_chars,
    )
    content = _long_text(30)

    messages = [
        SystemMessage(content="system"),
        HumanMessage(content=content, id="h1"),
    ]

    result = _run(mw, messages)
    assert result is not None, "token 超限应触发卸载"

    h1 = next(m for m in result if isinstance(m, HumanMessage))
    assert "已保存至" in h1.content
    assert "token超限" in h1.content, "应标明 token 超限触发"

    print("PASS: test_single_msg_token_limit_triggers_offload")


def test_toolmsg_offload_preserves_name():
    """单消息卸载 ToolMessage 时 name 字段应保留"""
    mw = _make_middleware(
        model=_ModelWithContext(max_input_tokens=10000),
        max_token_ratio=1.0,
        single_msg_ratio=0.0025,
        token_counter=_count_content_chars,
    )
    content = _long_text(30)

    messages = [
        SystemMessage(content="system"),
        HumanMessage(content="q", id="h1"),
        AIMessage(content="a", id="a1", tool_calls=[{"id": "tc1", "name": "big_tool", "args": {}}]),
        ToolMessage(content=content, tool_call_id="tc1", name="big_tool", id="t1"),
        HumanMessage(content="q2", id="h2"),
    ]

    result = _run(mw, messages)
    assert result is not None

    t1 = next(m for m in result if isinstance(m, ToolMessage))
    assert t1.tool_call_id == "tc1"
    assert t1.name == "big_tool", "卸载后 name 应保留"

    print("PASS: test_toolmsg_offload_preserves_name")


def test_concurrent_sessions_keep_archive_paths_isolated(tmp_path: Path):
    """同一中间件处理并发本地会话时，归档文件必须保留各自 thread_id。"""
    barrier = Barrier(2)

    class CoordinatedMiddleware(ContextManagerMiddleware):
        def _save_to_file(self, content: str, prefix: str) -> str:
            barrier.wait(timeout=5)
            return super()._save_to_file(content, prefix)

    mw = CoordinatedMiddleware(
        model=_ModelWithContext(max_input_tokens=100),
        file_store_path=str(tmp_path),
        max_token_ratio=1.0,
        single_msg_ratio=0.5,
        token_counter=_count_content_chars,
    )

    def run(thread_id: str, marker: str) -> None:
        mw.before_model(
            {
                "messages": [HumanMessage(content=marker * 2000, id=f"msg-{thread_id}")],
                "configurable": {"thread_id": thread_id},
            },
            None,
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [
            pool.submit(run, "session-A", "A"),
            pool.submit(run, "session-B", "B"),
        ]
        for future in futures:
            future.result()

    # Each readable archive also retains main's private native replay sidecar.
    archive_paths = sorted(tmp_path.glob("*.txt"))
    assert all(path.with_suffix(".json").is_file() for path in archive_paths)
    archive_names = [path.name for path in archive_paths]
    assert len(archive_names) == 2
    assert any("session-A" in name for name in archive_names)
    assert any("session-B" in name for name in archive_names)


# ---------------------------------------------------------------------------
# 测试 3: 总上下文 token 阈值触发归档
# ---------------------------------------------------------------------------

def test_total_tokens_triggers_archive():
    """总 token 超限触发归档"""
    mw = _make_middleware(
        model=_ModelWithContext(max_input_tokens=100),
        max_token_ratio=0.3,  # 上下文预算 30 tokens
        single_msg_ratio=1.0, # 单消息预算 30 tokens，不让单消息卸载干扰
        token_counter=_count_ten_tokens_per_message,
    )

    messages = [
        SystemMessage(content="sys"),
        HumanMessage(content="q1", id="h1"),
        AIMessage(content="a1", id="a1"),
        HumanMessage(content="q2", id="h2"),
        AIMessage(content="a2", id="a2"),
        HumanMessage(content="latest question", id="h3"),
    ]

    result = _run(mw, messages)
    assert result is not None, "总 token 超限应触发归档"

    # 最近的消息应保留
    has_latest = any("latest question" in str(m.content) for m in result)
    assert has_latest, "最近消息应保留"

    # 应有归档通知
    has_archive = any("[系统]" in str(m.content) for m in result)
    assert has_archive, "应包含归档通知"

    print("PASS: test_total_tokens_triggers_archive")


# ---------------------------------------------------------------------------
# 测试 4: 不触发压缩
# ---------------------------------------------------------------------------

def test_no_compression_small_messages():
    """消息量小时不触发任何压缩"""
    mw = _make_middleware()

    messages = [
        SystemMessage(content="system"),
        HumanMessage(content="hello", id="h1"),
        AIMessage(content="hi", id="a1"),
    ]

    result = _run(mw, messages)
    assert result is None, "小消息不应触发压缩"

    print("PASS: test_no_compression_small_messages")


# ---------------------------------------------------------------------------
# 测试 5: 压缩后消息顺序正确
# ---------------------------------------------------------------------------

def test_message_order_after_compression():
    """压缩后消息顺序: SystemMessage -> (归档通知嵌入 HumanMessage) -> 后续消息"""
    mw = _make_middleware(
        model=_ModelWithContext(max_input_tokens=100),
        max_token_ratio=0.4,
        single_msg_ratio=1.0,
        token_counter=_count_ten_tokens_per_message,
        short_content_chars=100,
    )

    messages = [
        SystemMessage(content="system"),
        HumanMessage(content="q1", id="h1"),
        AIMessage(content="a1", id="a1"),
        HumanMessage(content="final q", id="h2"),
        AIMessage(content="final a", id="a2"),
    ]

    result = _run(mw, messages)
    assert result is not None

    # 第一条应是 SystemMessage
    assert isinstance(result[0], SystemMessage), "第一条应是 SystemMessage"

    # 不应有连续两条 HumanMessage (会导致 API 400 错误)
    for i in range(len(result) - 1):
        if isinstance(result[i], HumanMessage) and isinstance(result[i + 1], HumanMessage):
            assert False, f"位置 {i} 和 {i+1} 出现连续 HumanMessage"

    print("PASS: test_message_order_after_compression")


# ---------------------------------------------------------------------------
# Responses payload / request-budget regressions (real LangChain messages)
# ---------------------------------------------------------------------------

import json
import pytest
from langchain.agents.middleware.types import ModelRequest
from langchain_core.language_models.fake_chat_models import FakeListChatModel
from context.context_manager import ConversationRoundData


def _responses_messages():
    ai = AIMessage(
        id="ai-responses",
        content=[
            {"type": "reasoning", "id": "rs_1", "encrypted_content": "opaque-replay", "summary": []},
            {"type": "text", "text": "visible answer", "id": "msg_1", "annotations": []},
        ],
        tool_calls=[{"name": "browser_snapshot", "args": {}, "id": "call_1"}],
        response_metadata={"id": "resp_1", "model_name": "fixture-model"},
        usage_metadata={"input_tokens": 12, "output_tokens": 3, "total_tokens": 15},
    )
    tool = ToolMessage(
        id="tool-1", name="browser_snapshot", tool_call_id="call_1",
        content=[{"type": "output_text", "text": "result " * 400}],
        status="error", artifact={"raw": {"ok": False, "source": "fixture"}},
        additional_kwargs={"provider": "fixture"}, response_metadata={"latency": 7},
    )
    return ai, tool


def test_uncompressed_responses_messages_keep_native_identity(tmp_path):
    ai, tool = _responses_messages()
    human = HumanMessage(content=[{"type": "input_text", "text": "question"}], id="h")
    messages = [human, ai, tool]
    before = [m.model_dump() for m in messages]
    mw = _make_middleware(file_store_path=str(tmp_path), recent_tool_messages_to_keep=3)
    assert mw.before_model({"messages": messages}, None) is None
    assert messages[1] is ai and messages[2] is tool
    assert [m.model_dump() for m in messages] == before


def test_context_display_projects_responses_text_without_reasoning(tmp_path):
    mw = _make_middleware(file_store_path=str(tmp_path))
    content = [
        {"type": "reasoning", "text": "private-thought", "encrypted_content": "opaque-replay"},
        {"type": "output_text", "text": "visible"},
        {"type": "input_text", "text": " question"},
        {"type": "refusal", "refusal": " refused"},
    ]
    assert mw._content_to_text(content) == "visible question refused"
    assert ConversationRoundData([AIMessage(content=content)]).full_text == "ai: visible question refused\n"


@pytest.mark.parametrize("mode", ["old-tool", "single-message"])
def test_compression_preserves_all_tool_metadata_and_archives_raw_payload(tmp_path, mode):
    ai, tool = _responses_messages()
    original = tool.model_dump()
    mw = _make_middleware(
        file_store_path=str(tmp_path), short_content_chars=20,
        recent_tool_messages_to_keep=0,
    )
    if mode == "old-tool":
        result = mw._compress_old_tool_messages([ai, tool])
    else:
        mw.single_msg_limit = 1
        result = mw._offload_heavy_messages([ai, tool])
    assert result[0] is ai
    replacement = result[1]
    assert replacement is not tool
    assert replacement.model_dump(exclude={"content"}) == tool.model_dump(exclude={"content"})
    assert "BEGIN PREVIEW" in replacement.content
    assert tool.model_dump() == original
    payloads = [json.loads(p.read_text()) for p in tmp_path.glob("*.json")]
    assert any(original in payload for payload in payloads), "offload must retain a full replay payload, not only display text"


def test_archive_keeps_full_call_result_and_latest_human_metadata(tmp_path):
    ai, tool = _responses_messages()
    human = HumanMessage(
        content=[{"type": "input_text", "text": "latest"}], id="h2", name="user-name",
        additional_kwargs={"provider": "fixture"}, response_metadata={"origin": "test"},
    )
    mw = _make_middleware(file_store_path=str(tmp_path))
    result = mw._archive_old_rounds([HumanMessage(content="old", id="h1"), ai, tool, human])
    assert len(result) == 1 and isinstance(result[0], HumanMessage)
    assert result[0].model_dump(exclude={"content"}) == human.model_dump(exclude={"content"})
    assert result[0].content[1:] == human.content
    payloads = [json.loads(p.read_text()) for p in tmp_path.glob("*.json")]
    assert any(ai.model_dump() in p and tool.model_dump() in p for p in payloads)
    text = "\n".join(p.read_text() for p in tmp_path.glob("*.txt"))
    assert "opaque-replay" not in text and "visible answer" in text


class _CountingRequestModel(FakeListChatModel):
    counted: list = []

    def get_num_tokens_from_messages(self, messages, tools=None):
        self.counted.append((list(messages), tools))
        return sum(len(m.content) if isinstance(m.content, str) else 10 for m in messages)


def test_request_budget_counts_actual_system_and_tool_schemas(tmp_path):
    model = _CountingRequestModel(responses=["unused"], profile={"max_input_tokens": 1000})
    mw = _make_middleware(
        model=model, file_store_path=str(tmp_path), max_token_ratio=1.0,
        single_msg_ratio=1.0,
    )
    schema = {"type": "function", "function": {"name": "large_tool", "description": "d" * 800,
              "parameters": {"type": "object", "properties": {}}}}
    latest = HumanMessage(content="latest", id="h2")
    request = ModelRequest(model=model, messages=[HumanMessage(content="old", id="h1"),
        AIMessage(content="reply", id="a1"), latest],
        system_message=SystemMessage(content="s" * 150), tools=[schema], state={"messages": []})
    captured = []
    response = AIMessage(content="handler-result")
    assert mw.wrap_model_call(request, lambda r: captured.append(r) or response) is response
    assert len(captured[0].messages) == 1, "fixed system/tool cost must trigger old-turn archive"
    assert captured[0].system_message is request.system_message
    assert captured[0].tools == [schema]
    assert len(request.messages) == 3, "request overrides must not mutate the original"
    assert model.counted, "use the actual request model's counter when available"


def test_native_archive_roundtrips_responses_payload_and_does_not_overwrite(tmp_path):
    from langchain_core.messages import messages_from_dict

    mw = _make_middleware(file_store_path=str(tmp_path))
    ai, tool = _responses_messages()
    first = mw._save_message_archive([ai, tool], "same-prefix")
    second = mw._save_message_archive([ai], "same-prefix")
    assert first != second
    payload_file = Path(first).with_suffix(".json")
    payload = json.loads(payload_file.read_text())
    restored = messages_from_dict([{"type": item["type"], "data": item} for item in payload])
    assert [m.model_dump() for m in restored] == [ai.model_dump(), tool.model_dump()]
    assert payload_file.stat().st_mode & 0o777 == 0o600


def test_real_openai_counter_typed_block_rejection_falls_back_without_payload_loss(tmp_path):
    from langchain_openai import ChatOpenAI

    # The model is never invoked. Its local counter currently rejects input_text.
    model = ChatOpenAI(model="gpt-4.1", api_key="fixture", base_url="http://127.0.0.1:1/v1")
    human = HumanMessage(content=[{"type": "input_text", "text": "question"}], id="h1")
    with pytest.raises(ValueError, match="Unrecognized content block type"):
        model.get_num_tokens_from_messages([human])
    ai, tool = _responses_messages()
    request = ModelRequest(model=model, messages=[human, ai, tool], tools=[])
    original = [m.model_dump() for m in request.messages]
    mw = _make_middleware(file_store_path=str(tmp_path), model=model)
    captured = []
    mw.wrap_model_call(request, lambda r: captured.append(r) or AIMessage(content="done"))
    assert captured[0] is request
    assert [m.model_dump() for m in captured[0].messages] == original


@pytest.mark.asyncio
async def test_async_request_budget_uses_the_same_fixed_cost_accounting(tmp_path):
    model = _CountingRequestModel(responses=["unused"], profile={"max_input_tokens": 100})
    mw = _make_middleware(model=model, max_token_ratio=1.0, file_store_path=str(tmp_path))
    request = ModelRequest(model=model, messages=[HumanMessage(content="old", id="h1"),
        AIMessage(content="reply", id="a1"), HumanMessage(content="new", id="h2")],
        system_message=SystemMessage(content="s" * 100))
    captured = []
    response = AIMessage(content="result")

    async def handler(r):
        captured.append(r)
        return response

    assert await mw.awrap_model_call(request, handler) is response
    assert len(captured[0].messages) == 1
    assert captured[0].system_message is request.system_message


def test_archive_preserves_recent_parallel_tool_pair_and_roles(tmp_path):
    mw = _make_middleware(file_store_path=str(tmp_path))
    ai, tool = _responses_messages()
    second = ToolMessage(content="ok", name="browser_tabs", tool_call_id="call_2", id="t2")
    ai.tool_calls.append({"name": "browser_tabs", "args": {}, "id": "call_2", "type": "tool_call"})
    messages = [HumanMessage(content="old", id="h0"), AIMessage(content="done", id="a0"),
                HumanMessage(content="new", id="h1"), ai, tool, second]
    result = mw._archive_old_rounds(messages)
    assert [m.type for m in result] == ["human", "ai", "tool", "tool"]
    assert result[1] is ai and result[2] is tool and result[3] is second
    assert {call["id"] for call in ai.tool_calls} == {m.tool_call_id for m in result[2:]}


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------

def main():
    tests = [
        test_old_tool_messages_compressed_recent_kept,
        test_short_tool_messages_not_compressed,
        test_tool_call_id_and_name_preserved,
        test_single_msg_token_limit_triggers_offload,
        test_toolmsg_offload_preserves_name,
        test_total_tokens_triggers_archive,
        test_no_compression_small_messages,
        test_message_order_after_compression,
    ]

    passed = 0
    failed = 0
    for test_fn in tests:
        try:
            test_fn()
            passed += 1
        except Exception as e:
            failed += 1
            print(f"FAIL: {test_fn.__name__}: {e}")
            import traceback
            traceback.print_exc()

    print(f"\n{'='*40}")
    print(f"  Results: {passed} passed, {failed} failed")
    print(f"{'='*40}")
    return failed == 0


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
