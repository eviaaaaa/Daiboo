import uvicorn
import webbrowser
from pathlib import Path
import time
import threading
import sys
import asyncio
from dotenv import load_dotenv

from utils.config import app_host, app_port

load_dotenv(dotenv_path=Path(__file__).resolve().parent / ".env")

# 为 Playwright 设置 Windows 事件循环策略
if sys.platform == 'win32':
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

def open_browser():
    # 给服务一点启动时间（增加到 5 秒，便于浏览器启动）
    time.sleep(5)
    host = app_host()
    display_host = "127.0.0.1" if host == "0.0.0.0" else host
    frontend_url = f"http://{display_host}:{app_port()}/"
    print(f"Opening frontend: {frontend_url}")
    webbrowser.open(frontend_url)

def main():
    # 在单独线程中打开浏览器
    threading.Thread(target=open_browser, daemon=True).start()

    # 运行 API 服务
    host = app_host()
    port = app_port()
    print(f"Starting API server on http://{host}:{port}")
    # 禁用 reload，确保事件循环策略在主进程中正确生效
    uvicorn.run("api:app", host=host, port=port, reload=False, loop="asyncio")

if __name__ == "__main__":
    main()
