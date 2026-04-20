import uvicorn
import webbrowser
from pathlib import Path
import time
import threading
import sys
import asyncio

# 为 Playwright 设置 Windows 事件循环策略
if sys.platform == 'win32':
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

def open_browser():
    # 给服务一点启动时间（增加到 5 秒，便于浏览器启动）
    time.sleep(5)
    frontend_path = Path(__file__).parent / "frontend" / "index.html"
    print(f"Opening frontend: {frontend_path}")
    webbrowser.open(frontend_path.as_uri())

def main():
    # 在单独线程中打开浏览器
    threading.Thread(target=open_browser, daemon=True).start()

    # 运行 API 服务
    print("Starting API server on http://localhost:8801")
    # 禁用 reload，确保事件循环策略在主进程中正确生效
    uvicorn.run("api:app", host="0.0.0.0", port=8801, reload=False, loop="asyncio")

if __name__ == "__main__":
    main()
