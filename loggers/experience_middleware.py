"""
经验记录中间件 - 在每轮对话结束后异步触发经验总结
"""
import asyncio
from langchain.agents.middleware import after_agent, types

from loggers.experience_summarizer import ExperienceSummarizer


async def _run_experience_summarizer(state: dict):
    """
    包装函数，用于捕获和打印异步任务中的异常
    """
    try:
        summarizer = ExperienceSummarizer()
        await summarizer.summarize_from_state(state)
    except Exception as e:
        session_id = state.get('configurable', {}).get('thread_id') or (state.get('messages', [{}])[0].id if state.get('messages') else 'unknown')
        turn_number = state.get('turn_number', 1)
        print(f"⚠️ 经验总结任务异常 (Session: {session_id[:8] if session_id != 'unknown' else 'unknown'}..., Turn: {turn_number}): {e}")
        import traceback
        traceback.print_exc()


@after_agent(can_jump_to="end")
async def log_experience(state: types.StateT, runtime) -> None:
    """
    经验记录中间件：在每轮对话结束后，异步触发经验总结
    
    工作流程：
    1. 直接将 state 传递给 ExperienceSummarizer
    2. 总结器从 state 中提取 session_id 和 turn_number
    3. 异步进行经验提炼，不阻塞主流程
    
    注意：
    - 使用 asyncio.ensure_future() 并保持任务引用，避免被垃圾回收
    - 任务会在事件循环的下一个迭代中执行（前提是主程序使用异步输入）
    """
    if not state:
        return
    
    session_id = state.get('configurable', {}).get('thread_id') or (state.get('messages', [{}])[0].id if state.get('messages') else 'unknown')
    turn_number = state.get('turn_number', 1)
    print(f"🚀 已触发经验总结任务 (Session: {session_id[:8] if session_id != 'unknown' else 'unknown'}..., Turn: {turn_number})")
    
    # 使用 ensure_future 并保持引用，避免任务被垃圾回收
    task = asyncio.ensure_future(_run_experience_summarizer(state))
    
    # 添加完成回调来追踪任务状态
    def _on_complete(future):
        try:
            future.result()  # 获取结果，如果有异常会在这里抛出
        except Exception:
            pass  # 异常已在 _run_experience_summarizer 中处理
    
    task.add_done_callback(_on_complete)
