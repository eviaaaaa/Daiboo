from pathlib import Path
import subprocess
import time
import atexit
import os
import socket
from contextlib import closing
from playwright.sync_api import sync_playwright, Browser, Playwright
import typing

# ========================
# 配置区
# ========================
BROWSER_PATH = os.getenv("BROWSER_PATH", r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe")
# 或 Chrome: r"C:\Program Files\Google\Chrome\Application\chrome.exe"

# 使用临时目录避免权限问题
USER_DATA_DIR = Path(os.getenv("USER_DATA_DIR", r"C:\playwright_edge_refined"))
DEBUGGING_PORT = int(os.getenv("DEBUGGING_PORT", "9222"))
DEBUGGING_URL = f"http://127.0.0.1:{DEBUGGING_PORT}"

# 用于保存浏览器子进程的全局变量
browser_process: typing.Optional[subprocess.Popen] = None

# 加载 .env 依赖
from dotenv import load_dotenv
load_dotenv()

# ========================
# 辅助函数
# ========================
def check_port_in_use(port: int) -> bool:
    """检查指定端口是否已被占用。"""
    with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as s:
        # connect_ex 返回 0 表示连接成功，即端口被占用
        return s.connect_ex(('127.0.0.1', port)) == 0

def cleanup_browser():
    """atexit 清理函数：如果是由本脚本启动的浏览器，则关闭它。"""
    global browser_process
    if browser_process:
        print("\n脚本退出，正在关闭由本脚本启动的浏览器进程...")
        browser_process.terminate()  # 发送终止信号
        try:
            # 等待进程终止，设置超时
            browser_process.wait(timeout=5)
            print("✅ 浏览器进程已关闭。")
        except subprocess.TimeoutExpired:
            print("⚠️ 关闭浏览器超时，强制终止。")
            browser_process.kill()  # 如果 terminate 不起作用，则强制杀死
        browser_process = None

# 注册清理函数，确保脚本退出时执行
atexit.register(cleanup_browser)

# ========================
# 核心功能
# ========================
def launch_or_connect_browser(p: Playwright) -> Browser:
    """
    检查调试端口。
    - 如果端口未被占用，则启动一个新的浏览器实例。
    - 如果端口已被占用，则直接连接到现有的浏览器实例。
    """
    global browser_process

    if check_port_in_use(DEBUGGING_PORT):
        print(f"端口 {DEBUGGING_PORT} 已被占用，将尝试直接连接...")
        try:
            browser = p.chromium.connect_over_cdp(DEBUGGING_URL)
            print("✅ 成功连接到已存在的浏览器实例。")
            return browser
        except Exception as e:
            raise RuntimeError(f"❌ 端口已被占用，但连接失败: {e}")
    else:
        print(f"端口 {DEBUGGING_PORT} 空闲，正在启动新的浏览器实例...")
        os.makedirs(USER_DATA_DIR, exist_ok=True)
        cmd = [
            BROWSER_PATH,
            f"--remote-debugging-port={DEBUGGING_PORT}",
            f"--user-data-dir={USER_DATA_DIR}",
            "--no-first-run",
            "--disable-default-apps",
            "--disable-popup-blocking",
            "--disable-gpu",
            "--start-maximized"
        ]
        print("启动命令:", " ".join(f'"{c}"' if " " in c else c for c in cmd))
        
        # 启动浏览器子进程
        # 去掉了 stdout 和 stderr 参数，这样浏览器的任何输出都会显示在你的终端里
        browser_process = subprocess.Popen(cmd)
        
        print("等待浏览器启动并开启调试端口...")
        for _ in range(20):  # 最多等待 10 秒
            try:
                import urllib.request
                with urllib.request.urlopen(f"{DEBUGGING_URL}/json/version", timeout=1) as resp:
                    if resp.status == 200:
                        print("✅ 新的浏览器实例已就绪。")
                        # 启动成功后，再通过 CDP 连接
                        return p.chromium.connect_over_cdp(DEBUGGING_URL)
            except Exception:
                time.sleep(0.5)
        
        # 如果超时，清理已启动的进程并抛出异常
        cleanup_browser()
        raise RuntimeError("❌ 浏览器启动超时或调试端口未开启。")

# ========================
# 主程序
# ========================
if __name__ == "__main__":
    with sync_playwright() as p:
        try:
            # 1. 启动或连接浏览器
            browser = launch_or_connect_browser(p)

            # 此时 browser 是 SyncBrowser 类型，符合你的工具要求
            print("成功获取 Browser 对象:", type(browser))

            # 2. 使用默认上下文（通常 contexts[0] 存在）
            # 如果浏览器是新启动的，contexts 列表为空
            if browser.contexts:
                context = browser.contexts[0]
                print("复用已存在的浏览器上下文。")
            else:
                context = browser.new_context()
                print("创建新的浏览器上下文。")
                
            # 如果上下文中没有页面，则创建一个
            if not context.pages:
                page = context.new_page()
            else:
                page = context.pages[0] # 复用已打开的第一个标签页

            page.goto("https://www.baidu.com")
            print("页面标题:", page.title())

            # 3. 保持打开（用于手动操作或后续自动化）
            input("\n按回车键退出...\n")

            # 4. 关闭连接（不会 kill 浏览器进程）
            # atexit 注册的 cleanup_browser 会在脚本最后负责关闭
            browser.close()

        except Exception as e:
            print(f"发生错误: {e}")