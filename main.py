import asyncio
import pprint
from typing import TYPE_CHECKING

from langchain.messages import HumanMessage
from langgraph.types import Command
from playwright.async_api import async_playwright

from utils.my_browser import launch_or_connect_browser
from agent_factory import create_browser_agent

if TYPE_CHECKING:
    from playwright.async_api import Browser as AsyncBrowser
    from playwright.sync_api import Browser as SyncBrowser


async def ainput(prompt: str = "") -> str:
    """
    异步版本的 input()，允许事件循环在等待输入时继续调度其他任务
    """
    return await asyncio.to_thread(input, prompt)

 

async def main():
    """
    主函数，持续接收用户输入直到输入 'exit' 或 'quit'
    支持动态 session 管理：输入 'new' 或 'reset' 创建新对话
    """
    import uuid
    
    async with async_playwright() as p:
        async with await launch_or_connect_browser(p) as browser:
            # 使用工厂函数创建 agent
            browser_agent = create_browser_agent(browser)

            print("=" * 60)
            print("NexusSurf 浏览器自动化助手")
            print("命令：'exit'/'quit' 退出 | 'new'/'reset' 新建对话")
            print("=" * 60)
            
            # 动态 session 管理
            current_session_id = None

            while True:
                # 从用户输入读取查询
                query = (await ainput("\n请输入您的查询：")).strip()

                # 检查是否退出
                if query.lower() in ['exit', 'quit']:
                    print("退出程序")
                    break
                
                # 检查是否创建新对话
                if query.lower() in ['new', 'reset', '新对话', '重置']:
                    current_session_id = uuid.uuid4().hex
                    print(f" 新对话已创建：{current_session_id[:8]}...")
                    continue

                if not query:
                    print("查询不能为空，请重新输入")
                    continue
                
                # 如果还没有 session，自动创建
                if current_session_id is None:
                    current_session_id = uuid.uuid4().hex
                    print(f" 自动创建对话：{current_session_id[:8]}...")

                print(f"\n用户查询：{query}")
                print(f"对话 ID：{current_session_id[:8]}...")

                inputs = {
                    "messages": [
                        HumanMessage(content=f"用户问题：{query}")
                    ]
                }
                print("\n 开始流式执行任务...")
                # 使用动态 session_id
                config = {"configurable": {"thread_id": current_session_id}, "recursion_limit": 80}
                
                # 循环处理流式输出和中断
                while True:
                    try:
                        async for chunk in browser_agent.astream(inputs, config=config, stream_mode="updates"):
                            mes = chunk.__str__()
                            pprint.pprint(mes[:2000])  # 只打印前2000字符，防止输出过长
                            print("\n" + "=" * 50 + "\n")
                        
                        # 如果流正常结束，跳出循环
                        break
                        
                    except Exception as e:
                        # 检查是否是中断异常 (LangGraph 的中断通常表现为执行停止，但我们需要检查状态)
                        # 注意：astream 可能会在中断时正常返回，我们需要检查 snapshot
                        print(f"执行过程中发生异常: {e}")
                        break
                    
                    finally:
                        # 每次执行完（或中断后），检查当前状态
                        snapshot = await browser_agent.aget_state(config)
                        if snapshot.next:
                            # 发现有挂起的中断任务
                            print("\n  检测到需要人工介入的任务！")
                            
                            # 获取中断详情 (通常在 tasks[0].interrupts 中)
                            # 这里简化处理，假设只有一个中断
                            
                            print("Agent 请求执行敏感操作。")
                            decision = (await ainput(">>> 请审批 (approve/reject): ")).strip().lower()
                            
                            if decision == "approve":
                                payload = {"decisions": [{"type": "approve"}]}
                            elif decision == "reject":
                                reason = await ainput("请输入拒绝理由: ")
                                payload = {"decisions": [{"type": "reject", "message": reason}]}
                            else:
                                print("无效输入，默认拒绝。")
                                payload = {"decisions": [{"type": "reject", "message": "Invalid user input."}]}
                                
                            # 使用 Command(resume=...) 恢复执行
                            # 更新 inputs 为 None，因为我们是恢复执行
                            inputs = Command(resume=payload)
                            print("🔄 恢复执行中...")
                            continue # 继续 while 循环，再次调用 astream
                        else:
                            # 没有后续任务，彻底结束
                            break


if __name__ == "__main__":
    asyncio.run(main())
