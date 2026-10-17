"""Experience generation must use the configured provider, entirely offline."""
from types import SimpleNamespace

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from loggers import experience_summarizer as module


@pytest.mark.parametrize("openai_configured", [True, False])
def test_experience_model_uses_selected_provider_without_temperature_override(monkeypatch, openai_configured):
    called = []
    marker = object()
    monkeypatch.setattr(module, "is_openai_compatible_configured", lambda: openai_configured, raising=False)
    monkeypatch.setattr(module, "create_openai_compatible_model",
        lambda **kwargs: called.append(("openai", kwargs)) or marker, raising=False)
    monkeypatch.setattr(module, "create_qwen_model", lambda **kwargs: called.append(("qwen", kwargs)) or marker)
    summarizer = module.ExperienceSummarizer()
    assert summarizer.llm is marker
    expected = ("openai", {"request_timeout": 120}) if openai_configured else ("qwen", {"temperature": 0.1})
    assert called == [expected]


@pytest.mark.asyncio
async def test_summary_projects_user_final_text_but_keeps_native_full_trace(monkeypatch):
    human = HumanMessage(content=[{"type": "input_text", "text": "question"}], id="session-fixture")
    tool = ToolMessage(content=[{"type": "output_text", "text": "tool result"}],
        tool_call_id="call_1", id="t1", name="browser_snapshot", status="error", artifact={"raw": "fixture"})
    ai = AIMessage(content=[{"type": "reasoning", "id": "rs_1", "encrypted_content": "opaque-replay", "summary": []},
        {"type": "output_text", "text": "answer", "id": "msg_1"}], id="a1", response_metadata={"id": "resp_1"})
    messages = [human, tool, ai]
    original = [m.model_dump() for m in messages]
    prompts, traces = [], []

    async def ainvoke(values):
        prompts.append(values[0].content)
        return AIMessage(content='{"is_valuable": false}')

    monkeypatch.setattr(module, "create_qwen_model", lambda **kwargs: SimpleNamespace(ainvoke=ainvoke))
    monkeypatch.setattr(module, "is_openai_compatible_configured", lambda: False, raising=False)
    monkeypatch.setattr(module, "format_trace_for_summary", lambda trace: traces.append(trace) or "summary")
    monkeypatch.setattr(module, "EXPERIENCE_SUMMARY_PROMPT", "{user_query}|{final_answer}|{trace_summary}")
    assert await module.ExperienceSummarizer().summarize_from_state({"messages": messages}) is None
    assert prompts == ["question|answer|summary"]
    # Formatter sees display-only copies; native messages keep all raw blocks.
    assert traces[0][-1]["content"] == "answer"
    assert traces[0][1]["content"] == "tool result"
    assert traces[0][1]["tool_call_id"] == "call_1"
    assert traces[0][1]["status"] == "error" and traces[0][1]["artifact"] == tool.artifact
    assert traces[0][-1]["response_metadata"] == ai.response_metadata
    assert [m.model_dump() for m in messages] == original


@pytest.mark.asyncio
async def test_real_summary_formatter_never_receives_reasoning_payload_as_text(monkeypatch):
    from prompt.experience_prompt import format_trace_for_summary

    prompts = []

    async def ainvoke(values):
        prompts.append(values[0].content)
        return AIMessage(content='{"is_valuable": false}')

    monkeypatch.setattr(module, "create_qwen_model", lambda **kwargs: SimpleNamespace(ainvoke=ainvoke))
    monkeypatch.setattr(module, "is_openai_compatible_configured", lambda: False)
    monkeypatch.setattr(module, "format_trace_for_summary", format_trace_for_summary)
    messages = [HumanMessage(content="question", id="fixture-session"), AIMessage(content=[
        {"type": "reasoning", "id": "rs_1", "encrypted_content": "opaque-replay", "summary": []},
        {"type": "output_text", "text": "visible answer", "id": "msg_1"}])]
    original = [m.model_dump() for m in messages]
    await module.ExperienceSummarizer().summarize_from_state({"messages": messages})
    assert prompts and "visible answer" in prompts[0]
    assert "opaque-replay" not in prompts[0] and "encrypted_content" not in prompts[0]
    assert [m.model_dump() for m in messages] == original
