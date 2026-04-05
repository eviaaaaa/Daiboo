"""
test_trace_sanitizer.py
测试多模态图文数据智能裁剪截断策略
"""
import sys
import os
import importlib.util

# 直接加载模块文件，跳过 utils/__init__.py（避免 dashscope 依赖）
_root = os.path.join(os.path.dirname(__file__), "..")
_spec = importlib.util.spec_from_file_location(
    "trace_sanitizer",
    os.path.join(_root, "utils", "trace_sanitizer.py")
)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)

sanitize_trace = _mod.sanitize_trace
TOOL_CONTENT_MAX_CHARS = _mod.TOOL_CONTENT_MAX_CHARS

# ── 辅助 ──────────────────────────────────────────────────────────────

def _make_trace(*msgs):
    """快速构造 serialized_trace 格式"""
    return list(msgs)

def _tool_msg(content: str) -> dict:
    return {"role": "tool", "content": content}

def _ai_msg(content: str) -> dict:
    return {"role": "ai", "content": content}

def _human_msg(content: str) -> dict:
    return {"role": "human", "content": content}

FAKE_BASE64 = "data:image/png;base64," + "A" * 5000
FAKE_RAW_B64 = "B" * 300  # 300 个 base64 字符，触发 raw 检测


# ── 测试用例 ───────────────────────────────────────────────────────────

def test_base64_inline_removed():
    """Tool 返回包含 data:image/png;base64 应被替换为占位符"""
    trace = _make_trace(_tool_msg(f"截图结果: {FAKE_BASE64} 完成"))
    result = sanitize_trace(trace)
    content = result[0]["content"]
    assert "data:image" not in content, "base64 应被移除"
    assert "BASE64_IMAGE_REMOVED" in content, "应有占位符"
    print(f"✅ test_base64_inline_removed | 裁剪后长度: {len(content)}")


def test_tool_content_truncated():
    """Tool 返回超长网页内容应被截断"""
    # 使用真实感的 HTML 内容，避免纯重复字符触发 raw base64 误判
    chunk = "<div class='content'><p>这是一段网页正文内容，包含中文和 English 混合文字。</p></div>\n"
    long_html = chunk * 200  # ~14000 chars
    trace = _make_trace(_tool_msg(long_html))
    result = sanitize_trace(trace)
    content = result[0]["content"]
    assert len(content) < len(long_html), f"内容应被截断: {len(content)} < {len(long_html)}"
    assert "truncated" in content, "应有截断标记"
    print(f"✅ test_tool_content_truncated | 原始: {len(long_html)} → 裁剪后: {len(content)}")


def test_short_tool_content_untouched():
    """正常短内容不应被截断"""
    msg = "点击成功，页面已跳转到首页"
    trace = _make_trace(_tool_msg(msg))
    result = sanitize_trace(trace)
    assert result[0]["content"] == msg
    print(f"✅ test_short_tool_content_untouched")


def test_multimodal_list_flattened():
    """list[dict] 多模态格式应被展平，图片块替换为占位符"""
    content = [
        {"type": "text", "text": "这是截图分析结果："},
        {"type": "image_url", "image_url": {"url": FAKE_BASE64}},
        {"type": "text", "text": "页面已加载完成"},
    ]
    trace = _make_trace({"role": "ai", "content": content})
    result = sanitize_trace(trace)
    c = result[0]["content"]
    assert isinstance(c, str), "应展平为 str"
    assert "这是截图分析结果" in c
    assert "页面已加载完成" in c
    assert "data:image" not in c, "图片 URL 应被移除"
    assert "IMAGE" in c, "应有图片占位符"
    print(f"✅ test_multimodal_list_flattened | 展平结果: {c[:80]}...")


def test_dashscope_dict_format():
    """DashScope 返回的 [{'text': '...'}] 格式应被正确展平"""
    content = [{"text": "分析完成，目标元素已定位"}]
    trace = _make_trace(_ai_msg(content))
    result = sanitize_trace(trace)
    assert result[0]["content"] == "分析完成，目标元素已定位"
    print(f"✅ test_dashscope_dict_format")


def test_tool_calls_base64_args_cleaned():
    """tool_calls 参数中的 base64 也应被清除"""
    tool_call = {
        "name": "analyze_image",
        "id": "call_abc",
        "args": {
            "image": FAKE_BASE64,
            "prompt": "描述这张图片"
        }
    }
    msg = {"role": "ai", "content": "正在分析...", "tool_calls": [tool_call]}
    trace = _make_trace(msg)
    result = sanitize_trace(trace)
    args = result[0]["tool_calls"][0]["args"]
    assert "BASE64 DATA REMOVED" in args["image"], "tool_call 参数中的 base64 应被清除"
    assert args["prompt"] == "描述这张图片", "正常参数不应被修改"
    print(f"✅ test_tool_calls_base64_args_cleaned")


def test_human_message_long_text_truncated():
    """Human 消息超长时也应截断"""
    long_text = "用户粘贴了大段文字：" + "测试" * 5000
    trace = _make_trace(_human_msg(long_text))
    result = sanitize_trace(trace)
    content = result[0]["content"]
    assert len(content) < len(long_text)
    assert "truncated" in content
    print(f"✅ test_human_message_long_text_truncated | 原始: {len(long_text)} → 裁剪后: {len(content)}")


if __name__ == "__main__":
    tests = [
        test_base64_inline_removed,
        test_tool_content_truncated,
        test_short_tool_content_untouched,
        test_multimodal_list_flattened,
        test_dashscope_dict_format,
        test_tool_calls_base64_args_cleaned,
        test_human_message_long_text_truncated,
    ]
    print("=" * 60)
    print("  AgentTrace 裁剪截断策略 单元测试")
    print("=" * 60)
    passed = 0
    for t in tests:
        try:
            t()
            passed += 1
        except Exception as e:
            print(f"❌ {t.__name__} FAILED: {e}")
    print("=" * 60)
    print(f"  结果: {passed}/{len(tests)} 通过")
    print("=" * 60)
