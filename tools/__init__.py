"""工具包。"""
from __future__ import annotations

from importlib import import_module
from typing import Any

__all__ = [
    "CaptureElementContextTool",
    "VLAnalysisTool",
    "delay_tool_call",
    "list_skills",
    "terminal_read",
    "terminal_write",
    "search_documents",
    "search_task_experience",
    "view_skill",
    "WebObserveTool",
    "HCaptchaSolverTool",
]

_EXPORTS = {
    "CaptureElementContextTool": ("tools.capture_element_context_tool", "CaptureElementContextTool"),
    "VLAnalysisTool": ("tools.vision_analysis_tool", "VLAnalysisTool"),
    "delay_tool_call": ("tools.delay_tool_call", "delay_tool_call"),
    "list_skills": ("tools.skill_tools", "list_skills"),
    "terminal_read": ("tools.terminal_tools", "terminal_read"),
    "terminal_write": ("tools.terminal_tools", "terminal_write"),
    "search_documents": ("tools.rag_tools", "search_documents"),
    "search_task_experience": ("tools.rag_tools", "search_task_experience"),
    "view_skill": ("tools.skill_tools", "view_skill"),
    "WebObserveTool": ("tools.web_observe_tool", "WebObserveTool"),
    "HCaptchaSolverTool": ("tools.hcaptcha_solver_tool", "HCaptchaSolverTool"),
}


def __getattr__(name: str) -> Any:
    if name not in _EXPORTS:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module_name, attr_name = _EXPORTS[name]
    value = getattr(import_module(module_name), attr_name)
    globals()[name] = value
    return value
