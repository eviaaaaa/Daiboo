"""
测试 Context Manager 压缩策略

覆盖:
- 旧 ToolMessage 压缩 (只保留最近 1 条完整)
- 单消息字符硬阈值 OR token 阈值
- tool_call_id / name 保留
- 总上下文字符阈值 OR token 阈值触发归档
"""
import sys
import os
import tempfile
from pathlib import Path

# 添加项目根目录到 Python 路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from langchain_core.messages import (
    HumanMessage, AIMessage, SystemMessage, ToolMessage, RemoveMessage,
)
from langchain_core.messages.utils import count_tokens_approximately
from context.context_manager import ContextManagerMiddleware


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _make_middleware(**overrides) -> ContextManagerMiddleware:
    """创建用于测试的 middleware，使用临时目录和小阈值便于触发"""
    defaults = dict(
        model=None,
        file_store_path=tempfile.mkdtemp(),
        max_token_ratio=0.8,
        single_msg_ratio=0.8,
        token_counter=count_tokens_approximately,
        recent_tool_messages_to_keep=1,
        tool_preview_chars=200,
        short_content_chars=1000,
        single_msg_max_chars=5000,       # 小阈值方便测试
        max_total_chars=10000,           # 小阈值方便测试
    )
    defaults.update(overrides)
    return ContextManagerMiddleware(**defaults)


def _long_text(n: int) -> str:
    """生成 n 个字符的填充文本"""
    base = "abcdefghij"  # 10 chars
    return (base * (n // 10 + 1))[:n]


def _run(mw: ContextManagerMiddleware, messages: list) -> list | None:
    """运行 before_model 并返回处理后的消息列表 (去除 RemoveMessage)"""
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
    # 短消息不应被压缩，且总量不超限 -> 可能返回 None
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
# 测试 2: 单消息字符硬阈值
# ---------------------------------------------------------------------------

def test_single_msg_char_limit_triggers_offload():
    """仅字符超限 (token 未超限) 时也应触发单消息卸载"""
    # single_msg_max_chars=5000, single_msg_limit 基于 128000*0.8=102400
    # 所以 6000 字符 -> 3000 estimated tokens < 102400 -> token 不超限
    # 但 6000 > 5000 -> 字符超限
    mw = _make_middleware(single_msg_max_chars=5000)
    content = _long_text(6000)

    messages = [
        SystemMessage(content="system"),
        HumanMessage(content=content, id="h1"),
    ]

    result = _run(mw, messages)
    assert result is not None, "字符超限应触发卸载"

    h1 = next(m for m in result if isinstance(m, HumanMessage))
    assert "已保存至" in h1.content, "应包含文件路径"
    assert "字符超限" in h1.content, "应标明字符超限触发"

    print("PASS: test_single_msg_char_limit_triggers_offload")


def test_single_msg_token_limit_triggers_offload():
    """仅 token 超限时也应触发单消息卸载"""
    # single_msg_limit = 128000*0.8 = 102400
    # 需要 content_len // 2 > 102400 -> content_len > 204800
    # 同时 single_msg_max_chars 设大到不触发
    mw = _make_middleware(single_msg_max_chars=999999)
    content = _long_text(210000)  # 210000 // 2 = 105000 > 102400

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
    mw = _make_middleware(single_msg_max_chars=5000)
    content = _long_text(6000)

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


# ---------------------------------------------------------------------------
# 测试 3: 总上下文字符阈值触发归档
# ---------------------------------------------------------------------------

def test_total_chars_triggers_archive():
    """总字符超限触发归档 (即使 token 未超限)"""
    # max_total_chars=10000, 每条消息 2500 字符 * 5 条 = 12500 > 10000
    # 但 token 估算 12500 / 4 ≈ 3125 远 < max_context_tokens
    mw = _make_middleware(
        max_total_chars=10000,
        single_msg_max_chars=99999,  # 不让单消息卸载干扰
    )

    msg_text = _long_text(2500)
    messages = [
        SystemMessage(content="sys"),
        HumanMessage(content=msg_text, id="h1"),
        AIMessage(content=msg_text, id="a1"),
        HumanMessage(content=msg_text, id="h2"),
        AIMessage(content=msg_text, id="a2"),
        HumanMessage(content="latest question", id="h3"),
    ]

    result = _run(mw, messages)
    assert result is not None, "总字符超限应触发归档"

    # 最近的消息应保留
    has_latest = any("latest question" in str(m.content) for m in result)
    assert has_latest, "最近消息应保留"

    # 应有归档通知
    has_archive = any("[系统]" in str(m.content) for m in result)
    assert has_archive, "应包含归档通知"

    print("PASS: test_total_chars_triggers_archive")


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
        max_total_chars=8000,
        single_msg_max_chars=99999,
        short_content_chars=100,
    )

    long = _long_text(5000)
    messages = [
        SystemMessage(content="system"),
        HumanMessage(content=long, id="h1"),
        AIMessage(content=long, id="a1"),
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
# main
# ---------------------------------------------------------------------------

def main():
    tests = [
        test_old_tool_messages_compressed_recent_kept,
        test_short_tool_messages_not_compressed,
        test_tool_call_id_and_name_preserved,
        test_single_msg_char_limit_triggers_offload,
        test_single_msg_token_limit_triggers_offload,
        test_toolmsg_offload_preserves_name,
        test_total_chars_triggers_archive,
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
