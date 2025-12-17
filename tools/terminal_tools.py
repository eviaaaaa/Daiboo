import subprocess
import re
import shutil
from langchain_core.tools import tool

# 检查常用 Bash 工具是否存在
HAS_GREP = shutil.which("grep") is not None
HAS_SED = shutil.which("sed") is not None
HAS_AWK = shutil.which("awk") is not None
HAS_HEAD = shutil.which("head") is not None
HAS_TAIL = shutil.which("tail") is not None

def _run_command(command: str) -> str:
    """安全运行命令的内部辅助函数。"""
    try:
        result = subprocess.run(
            ["powershell", "-Command", command],
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace'
        )
        output = result.stdout
        if result.stderr:
            output += f"\n[Stderr]:\n{result.stderr}"
        
        if not output and result.returncode == 0:
            return "命令执行成功（无输出）。"
        return output.strip()
    except Exception as e:
        return f"执行失败: {e}"

@tool
def terminal_read(command: str) -> str:
    """
    执行只读终端命令以检查文件或系统状态。
    支持: ls, cat, grep, head, tail, pwd, whoami, Get-Content, Select-String.
    
    示例:
    - "ls -r" : 递归列出文件
    - "cat file.txt | grep 'error'" : 搜索文本
    - "head -n 10 file.txt" : 读取前 10 行
    """
    # 1. 安全检查：禁止写入重定向和危险动词
    forbidden = [r">", r"Set-Content", r"Add-Content", r"rm ", r"del ", r"mv ", r"cp ", r"mkdir"]
    for p in forbidden:
        if re.search(p, command, re.IGNORECASE):
            return f"🚫 已拦截: 只读模式下不允许使用 '{p}'。如需修改请使用 'terminal_write'。"

    # 2. 智能适配 Bash 命令 (如果系统没有原生工具)
    # 如果用户习惯用 grep 但系统没有，自动替换为 PowerShell 的 Select-String
    if "grep" in command and not HAS_GREP:
        # 简单的替换逻辑，复杂情况建议直接用 Select-String
        command = command.replace("grep", "Select-String")
    
    if "head" in command and not HAS_HEAD:
        # head -n 5 -> Select-Object -First 5
        command = re.sub(r"head -n (\d+)", r"Select-Object -First \1", command)
        command = command.replace("head", "Select-Object -First 10")

    if "tail" in command and not HAS_TAIL:
        # tail -n 5 -> Select-Object -Last 5
        command = re.sub(r"tail -n (\d+)", r"Select-Object -Last \1", command)
        command = command.replace("tail", "Select-Object -Last 10")

    return _run_command(command)

@tool
def terminal_write(command: str) -> str:
    """
    执行写入/编辑终端命令以修改文件或目录。
    支持: echo, mkdir, rm, mv, cp, Set-Content, Add-Content.
    
    示例:
    - "echo 'hello' > file.txt" : 写入文件
    - "mkdir new_dir" : 创建目录
    - "rm old_file.txt" : 删除文件
    """
    # 允许的操作白名单 (宽松但必须是文件操作)
    allowed_verbs = [
        "echo", "mkdir", "md", "rm", "del", "remove-item",
        "mv", "move", "move-item", "cp", "copy", "copy-item",
        "set-content", "add-content", "new-item", ">", ">>"
    ]
    
    # 简单的启发式检查
    is_allowed = any(v in command.lower() for v in allowed_verbs)
    if not is_allowed:
        return "🚫 已拦截: 命令看起来不像支持的文件操作。"

    return _run_command(command)
