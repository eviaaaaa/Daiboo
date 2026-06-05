# -*- coding: utf-8 -*-
"""NaxusSurf 统一日志配置。

用法
    在 api.py / main.py 入口最顶部调用一次：
        from utils.logging import setup_logging
        setup_logging()

    之后所有模块直接从 loguru import logger 使用，无需额外配置：
        from loguru import logger
        logger.info("server started", port=8801)

环境变量
    LOG_LEVEL   日志级别（debug/info/warning/error），默认 info
    LOG_FORMAT  输出格式：pretty（开发用，带颜色）或 json（生产用，结构化），默认 pretty
    LOG_FILE    可选日志文件路径；不设置则只输出到 stderr
"""

from __future__ import annotations

import os
import sys

from loguru import logger

# 开发模式格式（带颜色 + 详细上下文）
_PRETTY_FMT = (
    "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
    "<level>{level: <8}</level> | "
    "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> | "
    "<level>{message}</level>"
)


def setup_logging(
    level: str | None = None,
    fmt: str | None = None,
    log_file: str | None = None,
) -> None:
    """初始化全局日志配置。（幂等：重复调用不叠加 handler）"""

    level = level or os.getenv("LOG_LEVEL", "INFO")
    fmt = fmt or os.getenv("LOG_FORMAT", "pretty")
    log_file = log_file or os.getenv("LOG_FILE")

    # 移除默认 handler，避免重复输出
    logger.remove()

    use_json = fmt == "json"

    # 主 handler
    logger.add(
        log_file or sys.stderr,
        level=level.upper(),
        format=_PRETTY_FMT,
        serialize=use_json,
        colorize=not use_json and log_file is None,
    )

    # 同时输出到 stderr（如果也写了文件）
    if log_file:
        logger.add(
            sys.stderr,
            level=level.upper(),
            format=_PRETTY_FMT,
            serialize=use_json,
            colorize=True,
        )

    logger.debug("Logging initialized", level=level, format=fmt)
