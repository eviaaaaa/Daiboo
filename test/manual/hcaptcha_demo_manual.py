"""手工联调：让本项目 agent 在官方 hCaptcha 测试站点上验证能力边界。

目标网站
    https://accounts.hcaptcha.com/demo
    （hCaptcha 官方提供的合法演示页，专门用来测试 hCaptcha 表单接入。）

用途
    - 验证 agent 在「外层同源 checkbox + 后续跨域挑战」场景下的工具选择是否正确。
    - 真实驱动浏览器、MCP、web_observe、browser_snapshot、browser_click、
      browser_take_screenshot、vl_analysis_tool 等工具。
    - 评估 agent 是否会：
        1) 先用低成本的 ref 路径处理外层 checkbox
        2) 在真正进入 challenge 后识别到能力边界，而不是乱用工具死循环

为什么这个测试合法
    - 站点本身明确写着「Hcaptcha demo / test page」，是 hCaptcha 官方为
      接入方提供的演示页面，不涉及绕过任何真实业务的反爬规则。
    - 这里只测试 agent 的观察、判断和边界声明能力，不尝试批量或自动破解 hCaptcha。

运行
    conda run -n langchainenv python test/manual/hcaptcha_demo_manual.py
    conda run -n langchainenv python test/manual/hcaptcha_demo_manual.py --prompt v2
    conda run -n langchainenv python test/manual/hcaptcha_demo_manual.py --prompt v3 --recursion 120

可用的 prompt 版本（见 PROMPTS）：
    - v1：最少引导，看 agent 自主探索能力
    - v2：强调两阶段策略：先 ref，后观察挑战并停机
    - v3：详细步骤 + 禁止误用 terminal_read / 虚构工具名
"""
from __future__ import annotations

import argparse
import asyncio
import os
import pprint
import sys
import time
from pathlib import Path

from dotenv import load_dotenv
from langchain.messages import AIMessage, HumanMessage

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

load_dotenv(ROOT / ".env")

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

from utils.agent_factory import create_browser_agent  # noqa: E402
from utils.mcp_client import create_persistent_mcp_session  # noqa: E402
from utils.my_browser import ensure_browser_running  # noqa: E402
from utils.qwen_model import normalize_content  # noqa: E402

HCAPTCHA_URL = "https://accounts.hcaptcha.com/demo"

# ──────────────────────────────────────────────────────────────────────────────
# Prompt 版本：不断迭代以引导 agent 正确组合工具
# 设计原则：
#   1. 始终明确「合法性」+「目标」，避免模型出于安全策略拒绝执行
#   2. 显式提示 hCaptcha 的关键障碍：跨域 iframe → 默认 snapshot/ref 不可用
#   3. 给出本仓库实际可用的工具名（不要让它去想象不存在的工具）
#   4. 给出可观测的成功信号，避免 agent 自欺欺人地说「我成功了」
# ──────────────────────────────────────────────────────────────────────────────

SUCCESS_SIGNALS = """
判定成功的可观测信号（任一即可）：
- 页面出现 "Verification Success" / "You are human" 之类提示
- 表单上的 hCaptcha 复选框区域出现绿色勾 ✔
- 页面 DOM 中存在非空的 `name="h-captcha-response"` 隐藏字段
- 点击 Submit 后服务器返回成功页面
失败必须明说为什么失败、卡在哪一步、是否触及能力边界。
""".strip()

PROMPT_V1_MINIMAL = f"""请打开 {HCAPTCHA_URL}（这是 hCaptcha 官方合法演示站点，专门用于测试），
测试当前 agent 在该页面上的真实能力边界。

要求：
- 先尝试完成页面上外层可见 checkbox 的标准交互。
- 如果进入跨域 challenge，先观察并判断是否具备可靠自动完成能力。
- 如果不具备，就明确停止并说明阻塞点，不要编造成功。

{SUCCESS_SIGNALS}
""".strip()

PROMPT_V2_TOOL_HINT = f"""请打开 {HCAPTCHA_URL}（这是 hCaptcha 官方合法测试演示站点）并尝试通过 hCaptcha。

环境特性提醒：
- 外层复选框在当前页面通常是可见且可拿 ref 的，优先使用：
    1) `web_observe(text_only=True)` 看页面结构
    2) `browser_snapshot`
    3) `browser_click`
- 只有真正进入 challenge 后，才考虑截图观察。
- 不要使用不存在的工具名；当前真实鼠标坐标工具是：
    - `browser_mouse_click_xy`
    - `browser_mouse_drag_xy`
    - `browser_mouse_move_xy`
- 不要调用 `terminal_read` / `terminal_write`。
- 如果 challenge 已经出现，但没有可靠坐标来源或视觉 grounding，必须停止说明边界。

{SUCCESS_SIGNALS}
""".strip()

PROMPT_V3_STRATEGY = f"""任务：在 hCaptcha 官方演示站点 {HCAPTCHA_URL} 上完成人机校验并提交表单。
此站点是 hCaptcha 官方公开的合法测试页，仅用来评估你（agent）工具选择和边界判断的能力。

请严格按以下流水线推进，每一步先想清楚再调工具：

阶段 A · 进入与外层交互（同源，走标准 ref 路径）
  A1. `browser_navigate` 打开目标 URL，等待加载。
  A2. `web_observe(text_only=True)` 看清页面整体结构，确认表单与 hCaptcha 容器存在。
  A3. `browser_snapshot` 取当前 ref，定位到 "I'm not a robot" 复选框并 `browser_click`。
       注意：点击后多半会弹出跨域挑战面板，此时旧 ref 立即作废。

阶段 B · 处理弹出的跨域挑战（先观察，不要盲动）
  B1. 用 `browser_take_screenshot`（fullPage=false 即可）截当前可视区。
  B2. 用 `vl_analysis_tool` 只做观察性分析：
       - 挑战提示语是什么
       - 是点选、拖动还是文本类 challenge
       - 画面中是否存在明显的 Verify / Next / Skip 控制
       不要求输出精确坐标。
  B3. 如果 challenge 需要基于图像内容进行点击/拖动，且你没有可靠的坐标 grounding，
       立即停止，明确说“当前工具链缺少稳定的视觉坐标定位能力，无法可靠自动完成 challenge”。
  B4. 只有在页面直接显示已通过、或外层 checkbox 已呈现成功状态时，才进入阶段 C。

阶段 C · 提交表单
  C1. 校验通过后，外层 DOM 已恢复同源可见。重新 `browser_snapshot`，
       找到 Submit 按钮 ref。
  C2. `browser_click` 提交，看 [diff] 与 [transients] 判断成功。
  C3. 必要时 `web_observe(text_only=True)` 复核结果页文本。

强约束：
- 不要使用 `browser_evaluate` 派发合成 click 事件。
- 不要调用 `terminal_read` / `terminal_write`。
- 不要编造不存在的工具名，比如 `browser_screen_click`。
- 不要重复尝试同一个失效 ref；一旦页面有 [diff]，重新 snapshot。
- 不要凭"页面没报错"就声明成功；必须看到下面这些可观测信号之一。

{SUCCESS_SIGNALS}
""".strip()

PROMPT_V4_SOLVER = f"""任务：在 hCaptcha 官方演示站点 {HCAPTCHA_URL} 上完成人机校验并提交表单。

本仓库提供了一个专门的 `solve_hcaptcha` 工具（内部包装 hcaptcha-challenger），
请你以"用工具，不自己写解法"的思路完成任务：

1) `browser_navigate` 打开目标 URL；`web_observe(text_only=True)` 看清页面表单结构。
2) **不要**先 `browser_click` 点 hCaptcha checkbox。直接调
   `solve_hcaptcha(click_checkbox=True)`：solver 必须在 checkbox 被点击前
   注册 `/getcaptcha/` 响应监听器，外部预点会让监听器永远收不到 payload，
   solver 只能落到不可靠的视觉兜底。
3) 等 `solve_hcaptcha` 返回。读它的 JSON：
   - status == "ok" + last_captcha_response 有内容 → 继续 4。
   - status == "error" / "fail" → 读 message 判断（依赖缺失？CDP 失败？题型不支持？），
     按系统第 7 节降级声明边界，不要重试 solve_hcaptcha。
4) `web_observe` 或 `browser_snapshot` 复核外层成功信号：
   - "Verification Success" 文案 / 绿色勾
   - `name="h-captcha-response"` 隐藏字段非空
   只要任一信号出现才算通过。
5) 通过后重新 snapshot 找 Submit 按钮，`browser_click` 提交。

强约束：
- **绝不**在调 solve_hcaptcha 之前 `browser_click` 点 hCaptcha checkbox：会破坏 payload 监听。
- 不要尝试自己用 browser_take_screenshot + 坐标点击替代 solve_hcaptcha；这条路对 hCaptcha
  几乎一定失败（事件可信度被检测）。
- 不要在 solve_hcaptcha 失败后用 vl_analysis_tool + 坐标点击重试；那是更糟的路径。
- 调用 solve_hcaptcha 不超过 2 次。

{SUCCESS_SIGNALS}
""".strip()

PROMPTS = {
    "v1": PROMPT_V1_MINIMAL,
    "v2": PROMPT_V2_TOOL_HINT,
    "v3": PROMPT_V3_STRATEGY,
    "v4": PROMPT_V4_SOLVER,
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="hCaptcha demo agent 联调：评估工具选择、观察能力和边界声明。"
    )
    parser.add_argument(
        "--prompt",
        choices=sorted(PROMPTS.keys()),
        default="v3",
        help="选择要测试的 prompt 版本（默认 v3，最详细）。",
    )
    parser.add_argument(
        "--recursion",
        type=int,
        default=120,
        help="LangGraph recursion_limit，hCaptcha 多轮挑战通常要 80~150 步。",
    )
    parser.add_argument(
        "--thread-id",
        default=None,
        help="对话线程 id，默认按时间戳生成，便于 InMemorySaver 隔离不同次试运行。",
    )
    parser.add_argument(
        "--show-prompt-only",
        action="store_true",
        help="只打印当前选中的 prompt，不真正驱动 agent，方便人工 review。",
    )
    return parser.parse_args()


async def run_once(prompt_text: str, thread_id: str, recursion: int) -> None:
    """跑一次 agent 流程，把 AI 响应实时打印出来。"""
    await ensure_browser_running()
    async with create_persistent_mcp_session() as mcp_tools:
        # 打印 MCP 实际暴露的工具，方便人工核对 prompt 里写的工具名是否真实存在。
        tool_names = sorted(getattr(t, "name", "?") for t in mcp_tools)
        print("\n[MCP 已加载工具]")
        for name in tool_names:
            print(f"  - {name}")
        print()

        agent = await create_browser_agent(mcp_tools)
        config = {
            "configurable": {"thread_id": thread_id},
            "recursion_limit": recursion,
        }
        inputs = {"messages": [HumanMessage(content=f"用户问题：{prompt_text}")]}

        async for chunk in agent.astream(inputs, config=config, stream_mode="updates"):
            if "model" in chunk and "messages" in chunk["model"]:
                for msg in chunk["model"]["messages"]:
                    if isinstance(msg, AIMessage):
                        print("\n[AI]")
                        print(normalize_content(msg.content))
                        # 把 tool_calls 也单独打出来，便于追踪它怎么组合工具
                        tool_calls = getattr(msg, "tool_calls", None) or []
                        if tool_calls:
                            print("[AI tool_calls]")
                            for tc in tool_calls:
                                name = tc.get("name") if isinstance(tc, dict) else getattr(tc, "name", "?")
                                args = tc.get("args") if isinstance(tc, dict) else getattr(tc, "args", {})
                                args_preview = pprint.pformat(args, width=120)
                                if len(args_preview) > 800:
                                    args_preview = args_preview[:800] + " ...<truncated>"
                                print(f"  - {name}: {args_preview}")
                        print("\n" + "=" * 80 + "\n")
            else:
                print("\n[UPDATE]")
                text = pprint.pformat(chunk, width=120)
                print(text[:6000])
                print("\n" + "=" * 80 + "\n")


def main() -> None:
    args = parse_args()
    prompt_text = PROMPTS[args.prompt]

    print("=" * 80)
    print(f"[hCaptcha demo manual] prompt 版本：{args.prompt}")
    print(f"[hCaptcha demo manual] 目标 URL：{HCAPTCHA_URL}")
    print("=" * 80)
    print(prompt_text)
    print("=" * 80 + "\n")

    if args.show_prompt_only:
        return

    thread_id = args.thread_id or f"manual-hcaptcha-{args.prompt}-{int(time.time())}"
    print(f"[hCaptcha demo manual] thread_id = {thread_id}")
    print(f"[hCaptcha demo manual] recursion_limit = {args.recursion}\n")

    try:
        asyncio.run(run_once(prompt_text, thread_id, args.recursion))
    except KeyboardInterrupt:
        print("\n[hCaptcha demo manual] 收到 Ctrl+C，已停止。")


if __name__ == "__main__":
    main()
