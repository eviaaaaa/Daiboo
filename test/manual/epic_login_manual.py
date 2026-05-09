"""手工联调：驱动当前 agent 尝试登录 Epic Games。

用途：
- 验证真实运行链路：浏览器启动 -> MCP 会话 -> agent -> Epic 登录页
- 只测试登录流程本身，不做站内其他操作
- 若出现验证码、2FA、人机校验或系统弹窗，应立刻停止并报告阻塞点

运行：
    conda run -n langchainenv python test/manual/epic_login_manual.py

环境变量：
    EPIC_EMAIL
    EPIC_PASSWORD
"""
from __future__ import annotations

import asyncio
import os
import pprint
import sys
from pathlib import Path

from dotenv import load_dotenv
from langchain.messages import AIMessage, HumanMessage

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

load_dotenv(ROOT / ".env")

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

from utils.agent_factory import create_browser_agent
from utils.mcp_client import create_persistent_mcp_session
from utils.my_browser import ensure_browser_running
from utils.qwen_model import normalize_content


def _require_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"缺少环境变量 {name}，请写入 .env 或当前 shell 后再运行。")
    return value


EPIC_EMAIL = _require_env("EPIC_EMAIL")
EPIC_PASSWORD = _require_env("EPIC_PASSWORD")

PROMPT = f"""打开 Epic Games 登录页面并尝试登录。
账号邮箱：{EPIC_EMAIL}
密码：{EPIC_PASSWORD}
要求：
1. 只执行登录，不做其他站内操作。
2. 如果出现验证码、二次验证、人机校验、系统弹窗，立刻停止并报告阻塞点。
3. 只有在明确看到已登录状态、账户页面、或用户头像/账户菜单等可靠登录成功信号后，才算成功。
4. 成功或失败都给出简短结论。"""


async def main() -> None:
    await ensure_browser_running()
    async with create_persistent_mcp_session() as mcp_tools:
        agent = await create_browser_agent(mcp_tools)
        config = {
            "configurable": {"thread_id": "manual-epic-login-test"},
            "recursion_limit": 80,
        }
        inputs = {"messages": [HumanMessage(content=PROMPT)]}

        async for chunk in agent.astream(inputs, config=config, stream_mode="updates"):
            if "agent" in chunk and "messages" in chunk["agent"]:
                for msg in chunk["agent"]["messages"]:
                    if isinstance(msg, AIMessage):
                        print("\n[AI]")
                        print(normalize_content(msg.content))
                        print("\n" + "-" * 80 + "\n")
            else:
                print("\n[chunk]")
                text = pprint.pformat(chunk, width=120)
                print(text[:6000])
                print("\n" + "-" * 80 + "\n")


if __name__ == "__main__":
    asyncio.run(main())
