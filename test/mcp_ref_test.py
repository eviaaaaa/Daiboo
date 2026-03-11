"""最小化测试：验证持久 MCP session 下 snapshot-ref 是否正常工作"""
import asyncio
import re
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.my_browser import ensure_browser_running
from utils.mcp_client import create_persistent_mcp_session


async def main():
    await ensure_browser_running()

    async with create_persistent_mcp_session() as tools:
        tool_map = {t.name: t for t in tools}
        print(f"[1] 工具数: {len(tools)}")

        # 导航
        print("[2] 导航到 saucedemo.com...")
        await tool_map["browser_navigate"].ainvoke({"url": "https://www.saucedemo.com/"})

        await asyncio.sleep(2)

        # 拍快照
        print("[3] 拍摄快照...")
        snapshot = await tool_map["browser_snapshot"].ainvoke({})
        print(snapshot[:400])

        # 提取 ref
        match = re.search(r'textbox "Username" \[ref=(e\d+)\]', snapshot)
        if not match:
            print("  未找到 Username ref")
            return
        ref = match.group(1)
        print(f"  Username ref: {ref}")

        # 填写
        print(f"[4] browser_type(ref={ref}, text='standard_user')...")
        try:
            result = await tool_map["browser_type"].ainvoke({"ref": ref, "text": "standard_user"})
            print(f"  OK: {result[:200]}")
        except Exception as e:
            print(f"  FAIL: {e}")
            return

        # 确认
        print("[5] 再次快照确认...")
        snapshot2 = await tool_map["browser_snapshot"].ainvoke({})
        print(snapshot2[:400])
        print("\nDONE")


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    asyncio.run(main())
