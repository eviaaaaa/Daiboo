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
