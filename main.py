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

 

async def main():
    """
    主函数 - 交互式版本，持续接收用户输入直到输入 'exit' 或 'quit'
    """
    async with async_playwright() as p:
        async with await launch_or_connect_browser(p) as browser:
            # 使用工厂函数创建 agent
            browser_agent = create_browser_agent(browser)

            print("=" * 60)
            print("NexusSurf 浏览器自动化助手")
            print("输入 'exit' 或 'quit' 退出程序")
            print("=" * 60)

            while True:
                # 从用户输入读取查询
                query = input("\n请输入您的查询：").strip()

                # 检查是否退出
                if query.lower() in ['exit', 'quit']:
                    print("退出程序")
                    break

                if not query:
                    print("查询不能为空，请重新输入")
                    continue

                print("\n用户查询：", query)

                inputs = {
                    "messages": [
                        HumanMessage(content=f"用户问题：{query}")
                    ]
                }
                print("\n🚀 开始流式执行任务...")
                # 增加递归限制以支持更长的交互流程
                # 修正 config 结构，将 thread_id 放入 configurable
                config = {"configurable": {"thread_id": "session_1"}, "recursion_limit": 80}
                
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
                            print("\n⚠️  检测到需要人工介入的任务！")
                            
                            # 获取中断详情 (通常在 tasks[0].interrupts 中)
                            # 这里简化处理，假设只有一个中断
                            # 注意：LangGraph 的 API 可能会变动，这里基于通用逻辑
                            
                            print("Agent 请求执行敏感操作。")
                            decision = input(">>> 请审批 (approve/reject): ").strip().lower()
                            
                            if decision == "approve":
                                payload = {"decisions": [{"type": "approve"}]}
                            elif decision == "reject":
                                reason = input("请输入拒绝理由: ")
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
