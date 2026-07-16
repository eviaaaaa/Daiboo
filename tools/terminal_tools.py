import os
import re
import shutil
import subprocess
import sys
from langchain_core.tools import tool

# 检查常用 Bash 工具是否存在
HAS_GREP = shutil.which("grep") is not None
HAS_HEAD = shutil.which("head") is not None
HAS_TAIL = shutil.which("tail") is not None


def _env_positive_number(name: str, default: float) -> float:
    try:
        value = float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default
    return value if value > 0 else default


def _select_shell(platform_name: str | None = None) -> list[str]:
    """按平台选择 shell；Windows 优先 pwsh，POSIX 优先 bash。"""
    platform_name = platform_name or sys.platform
    if platform_name.startswith("win"):
        for executable in ("pwsh", "powershell"):
            path = shutil.which(executable)
            if path:
                return [path, "-Command"]
        raise FileNotFoundError("Neither pwsh nor powershell is available")

    for executable in ("bash", "sh"):
        path = shutil.which(executable)
        if path:
            return [path, "-lc"]
    raise FileNotFoundError("Neither bash nor sh is available")


def _truncate_output(output: str, max_output_chars: int) -> str:
    if len(output) <= max_output_chars:
        return output
    omitted = len(output) - max_output_chars
    return f"{output[:max_output_chars]}\n[输出已截断，省略 {omitted} 个字符]"


def _run_command(
    command: str,
    *,
    timeout_seconds: float | None = None,
    max_output_chars: int | None = None,
) -> str:
    """跨平台执行命令，限制时间和输出，并始终返回退出码。"""
    timeout_seconds = timeout_seconds or _env_positive_number("TERMINAL_TIMEOUT_SECONDS", 30.0)
    if max_output_chars is None:
        max_output_chars = int(_env_positive_number("TERMINAL_MAX_OUTPUT_CHARS", 20000))
    try:
        result = subprocess.run(
            [*_select_shell(), command],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired as exc:
        partial_stdout = exc.stdout.decode("utf-8", "replace") if isinstance(exc.stdout, bytes) else (exc.stdout or "")
        partial_stderr = exc.stderr.decode("utf-8", "replace") if isinstance(exc.stderr, bytes) else (exc.stderr or "")
        partial = partial_stdout
        if partial_stderr:
            partial += f"\n[Stderr]:\n{partial_stderr}"
        partial = _truncate_output(partial.strip(), max_output_chars) if partial else ""
        suffix = f"\n{partial}" if partial else ""
        return f"执行超时（{timeout_seconds:g} 秒）。{suffix}".strip()
    except Exception as exc:
        return f"执行失败: {exc}"

    output = result.stdout or ""
    if result.stderr:
        output += f"\n[Stderr]:\n{result.stderr}"
    output = _truncate_output(output.strip(), max_output_chars) if output else "命令执行成功（无输出）。"
    return f"[Exit code: {result.returncode}]\n{output}"


@tool
def terminal_read(command: str) -> str:
    """
    执行只读终端命令以检查文件或系统状态。
    支持: ls, cat, grep, head, tail, pwd, whoami, Get-Content, Select-String.
    """
    forbidden = [r">", r"Set-Content", r"Add-Content", r"rm ", r"del ", r"mv ", r"cp ", r"mkdir"]
    for pattern in forbidden:
        if re.search(pattern, command, re.IGNORECASE):
            return f"🚫 已拦截: 只读模式下不允许使用 '{pattern}'。如需修改请使用 'terminal_write'。"

    if "grep" in command and not HAS_GREP:
        command = command.replace("grep", "Select-String")
    if "head" in command and not HAS_HEAD:
        command = re.sub(r"head -n (\d+)", r"Select-Object -First \1", command)
        command = command.replace("head", "Select-Object -First 10")
    if "tail" in command and not HAS_TAIL:
        command = re.sub(r"tail -n (\d+)", r"Select-Object -Last \1", command)
        command = command.replace("tail", "Select-Object -Last 10")

    return _run_command(command)


@tool
def terminal_write(command: str) -> str:
    """
    执行写入/编辑终端命令以修改文件或目录。
    支持: echo, mkdir, rm, mv, cp, Set-Content, Add-Content.
    """
    allowed_verbs = [
        "echo", "mkdir", "md", "rm", "del", "remove-item",
        "mv", "move", "move-item", "cp", "copy", "copy-item",
        "set-content", "add-content", "new-item", ">", ">>",
    ]

    if not any(verb in command.lower() for verb in allowed_verbs):
        return "🚫 已拦截: 命令看起来不像支持的文件操作。"

    return _run_command(command)
