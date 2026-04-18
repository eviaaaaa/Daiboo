from pathlib import Path
import asyncio
import subprocess
import atexit
import os
import typing
from dotenv import load_dotenv

# 加载 .env 依赖
load_dotenv()

# ========================
# 配置区
# ========================
BROWSER_PATH = os.getenv("BROWSER_PATH", r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe")
# 或 Chrome: r"C:\Program Files\Google\Chrome\Application\chrome.exe"

# 使用临时目录避免权限问题
USER_DATA_DIR = Path(os.getenv("USER_DATA_DIR", r"C:\playwright_edge_refined"))
DEBUGGING_PORT = int(os.getenv("DEBUGGING_PORT", "9222"))

# 用于保存浏览器子进程的全局变量
browser_process: typing.Optional[subprocess.Popen] = None

# ========================
# 辅助函数
# ========================
async def check_port_in_use(port: int) -> bool:
    """异步检查指定端口是否已被占用。"""
    try:
        _, writer = await asyncio.open_connection('127.0.0.1', port)
        writer.close()
        await writer.wait_closed()
        return True
    except (ConnectionRefusedError, OSError):
        return False


def cleanup_browser():
    """atexit 清理函数：如果是由本脚本启动的浏览器，则关闭它。"""
    global browser_process
    if browser_process:
        print("\n脚本退出，正在关闭由本脚本启动的浏览器进程...")
        browser_process.terminate()  # 发送终止信号
        try:
            # 等待进程终止，设置超时
            browser_process.wait(timeout=5)
            print("浏览器进程已关闭。")
        except subprocess.TimeoutExpired:
            print("关闭浏览器超时，强制终止。")
            browser_process.kill()  # 如果 terminate 不起作用，则强制杀死
        browser_process = None

# 注册清理函数，确保脚本退出时执行
atexit.register(cleanup_browser)


# ========================
# 核心功能
# ========================
async def ensure_browser_running(port: int = None):
    """确保浏览器进程运行在指定端口（仅启动进程，不返回 Browser 对象）"""
    port = port or DEBUGGING_PORT
    if await check_port_in_use(port):
        print(f"端口 {port} 已有浏览器运行，跳过启动。")
        return

    global browser_process
    print(f"端口 {port} 空闲，正在启动新的浏览器实例...")
    os.makedirs(USER_DATA_DIR, exist_ok=True)
    cmd = [
        BROWSER_PATH,
        f"--remote-debugging-port={port}",
        f"--user-data-dir={USER_DATA_DIR}",
        "--no-first-run",
        "--disable-default-apps",
        "--disable-popup-blocking",
        "--disable-gpu",
        "--start-maximized"
    ]
    print("启动命令:", " ".join(f'"{c}"' if " " in c else c for c in cmd))
    browser_process = subprocess.Popen(cmd)

    print("等待浏览器启动并开启调试端口...")
    for _ in range(20):
        if await check_port_in_use(port):
            print("浏览器实例已就绪。")
            return
        await asyncio.sleep(0.5)

    cleanup_browser()
    raise RuntimeError("浏览器启动超时或调试端口未开启。")
