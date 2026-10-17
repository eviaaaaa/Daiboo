# -*- coding: utf-8 -*-
"""测试 utils/logging.py 日志配置模块。"""

import io
import json

import pytest
from loguru import logger

from utils.logging import setup_logging


class CaptureHandler:
    """将 loguru 输出捕获到 StringIO 以便断言。"""

    def __init__(self):
        self.stream = io.StringIO()

    def write(self, message: str) -> None:
        self.stream.write(message)

    def flush(self) -> None:
        pass

    def getvalue(self) -> str:
        return self.stream.getvalue()


@pytest.fixture(autouse=True)
def _reset_logging() -> None:
    """每个测试前重置 loguru 配置。"""
    logger.remove()
    yield
    logger.remove()


def test_setup_logging_pretty_mode() -> None:
    """pretty 模式输出包含消息和级别。"""
    cap = CaptureHandler()
    logger.remove()
    logger.add(cap, format="{level} | {message}", colorize=False)
    logger.info("hello world")
    output = cap.getvalue()
    assert "hello world" in output
    assert "INFO" in output


def test_setup_logging_json_mode() -> None:
    """JSON 模式（serialize=True）输出合法 JSON 行。"""
    cap = CaptureHandler()
    logger.remove()
    logger.add(cap, format="{message}", serialize=True, colorize=False)
    logger.info("structured test")
    output = cap.getvalue()
    parsed = json.loads(output.strip())
    assert parsed["record"]["message"] == "structured test"
    assert "text" in parsed  # loguru serialize 格式


def test_setup_logging_from_env(monkeypatch) -> None:
    """通过环境变量 LOG_LEVEL 控制日志级别。"""
    monkeypatch.setenv("LOG_LEVEL", "ERROR")
    cap = CaptureHandler()
    setup_logging(fmt="pretty")
    logger.remove()
    logger.add(cap, format="{level} | {message}", level="ERROR", colorize=False)
    logger.info("should not appear")
    logger.error("should appear")
    output = cap.getvalue()
    assert "should not appear" not in output
    assert "should appear" in output


def test_setup_logging_json_production() -> None:
    """setup_logging(fmt='json') 使用 serialize=True，产生 JSON 行。"""
    cap = CaptureHandler()
    logger.remove()
    logger.add(cap, format="{message}", serialize=True, colorize=False)
    logger.bind(request_id="abc").info("with context")
    output = cap.getvalue()
    parsed = json.loads(output.strip())
    assert parsed["record"]["message"] == "with context"
    assert parsed["record"]["extra"]["request_id"] == "abc"


def test_setup_logging_idempotent() -> None:
    """重复调用 setup_logging 不会崩溃。"""
    setup_logging(fmt="pretty")
    setup_logging(fmt="pretty")
    logger.info("idempotent test")


@pytest.mark.asyncio
async def test_final_response_log_separates_display_from_native_archive(tmp_path, monkeypatch):
    from langchain_core.messages import AIMessage, ToolMessage
    from loggers.screen_logger import log_agent_response

    monkeypatch.chdir(tmp_path)
    ai = AIMessage(content=[
        {"type": "reasoning", "id": "rs_1", "encrypted_content": "opaque-replay", "summary": []},
        {"type": "output_text", "text": "visible answer", "id": "msg_1"},
    ], id="a1", response_metadata={"id": "resp_1"})
    tool = ToolMessage(content="tool result", id="t1", tool_call_id="c1", name="browser_snapshot",
                       artifact={"raw": "fixture"}, status="error", response_metadata={"latency": 1})
    before = [m.model_dump() for m in [ai, tool]]
    await log_agent_response.aafter_agent({"messages": [ai, tool]}, None)
    display = "\n".join(p.read_text() for p in tmp_path.rglob("*.txt"))
    assert "visible answer" in display
    assert "opaque-replay" not in display and "encrypted_content" not in display
    archives = [json.loads(p.read_text()) for p in tmp_path.rglob("*.json")]
    assert before in archives
    assert [m.model_dump() for m in [ai, tool]] == before


@pytest.mark.asyncio
async def test_database_trace_retains_native_metadata_with_display_text(monkeypatch):
    import asyncio
    from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
    from loggers import screen_logger

    ai = AIMessage(content=[{"type": "output_text", "text": "answer"},
        {"type": "reasoning", "encrypted_content": "opaque-replay", "summary": []}],
        id="a1", response_metadata={"id": "resp_1"},
        usage_metadata={"input_tokens": 12, "output_tokens": 4, "total_tokens": 16})
    tool = ToolMessage(content="tool result", id="t1", tool_call_id="c1", name="browser_snapshot",
        status="error", artifact={"ok": False}, response_metadata={"latency": 1})
    messages = [HumanMessage(content="question", id="session-fixture"), tool, ai]
    saved = []
    monkeypatch.setattr(screen_logger, "save_agent_trace_to_pgvector", saved.append)
    await screen_logger.log_response_to_database.aafter_agent({"messages": messages}, None)
    await asyncio.sleep(0)
    assert len(saved) == 1
    trace = saved[0]
    tool_data, ai_data = trace.full_trace[1:]
    assert tool_data["tool_call_id"] == "c1"
    assert tool_data["status"] == "error" and tool_data["artifact"] == {"ok": False}
    assert tool_data["response_metadata"] == {"latency": 1}
    assert ai_data["response_metadata"] == {"id": "resp_1"}
    assert ai_data["usage_metadata"] == ai.usage_metadata
    assert ai_data["content"] == "answer" and trace.final_answer == "answer"
    assert trace.token_usage == {"input": 12, "output": 4, "total": 16}
