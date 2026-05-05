"""simphtml 内部模块。

源自 https://github.com/lsdefine/GenericAgent (MIT License) 的 simphtml.py，
移植到本仓库做 LLM-friendly 的页面观察。详见 docx/genericagent_investigation.md。

模块组织：
- opthtml.js / find_main_list.js: 注入到浏览器执行的 JS（不直接 import，由 Python 读取为字符串）
- observer.py: 共享 helper（find/build/normalize + observe_simplified + 瞬时文本监视器），被 web_observe_tool 与 diff_middleware 共用
- post_process.py: BeautifulSoup 二次清洗 + smart_truncate 预算式裁切
- diff.py: 简化 HTML 之间的 signature diff（供 web_observe 和 diff_middleware 共用）
"""
from tools._simphtml.post_process import optimize_html_for_tokens, smart_truncate
from tools._simphtml.diff import find_changed_elements
from tools._simphtml.observer import (
    OPTHTML_JS,
    EVALUATE_TOOL_NAME,
    find_evaluate_tool,
    build_evaluate_function,
    normalize_evaluate_result,
    observe_simplified,
    start_transient_monitor,
    stop_transient_monitor,
)

__all__ = [
    "optimize_html_for_tokens",
    "smart_truncate",
    "find_changed_elements",
    "OPTHTML_JS",
    "EVALUATE_TOOL_NAME",
    "find_evaluate_tool",
    "build_evaluate_function",
    "normalize_evaluate_result",
    "observe_simplified",
    "start_transient_monitor",
    "stop_transient_monitor",
]
