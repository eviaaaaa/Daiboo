"""
测试新的 Context Manager 压缩策略
"""
import sys
from pathlib import Path

# 添加项目根目录到 Python 路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from langchain_core.messages import HumanMessage, AIMessage, SystemMessage, RemoveMessage  # noqa: E402
from langchain_core.messages.utils import count_tokens_approximately  # noqa: E402
from context.context_manager import ContextManagerMiddleware  # noqa: E402
from utils import create_qwen_model  # noqa: E402


def create_long_content(base_text: str, target_tokens: int) -> str:
    """创建指定 token 数量的内容"""
    # 粗略估计：1个中文字符约等于2个token
    # 为了确保达到目标，多生成一些
    repeat_times = (target_tokens // 2) + 1000
    return base_text * repeat_times


def print_separator(title: str):
    """打印分隔线"""
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}\n")


def test_no_compression():
    """测试场景 0: 消息量小，不触发压缩"""
    print_separator("测试场景 0: 消息量小，不触发压缩")
    
    model = create_qwen_model()
    context_manager = ContextManagerMiddleware(
        model=model,
        max_token_ratio=0.8,
        single_msg_ratio=0.8
    )
    
    messages = [
        SystemMessage(content="你是一个有帮助的助手"),
        HumanMessage(content="你好，请介绍一下Python"),
        AIMessage(content="Python是一种高级编程语言..."),
        HumanMessage(content="谢谢"),
        AIMessage(content="不客气！"),
    ]
    
    print(f"总 token 数: {count_tokens_approximately(messages)}")
    print(f"限制: {context_manager.max_context_tokens}")
    
    state = {"messages": messages}
    result = context_manager.before_model(state, None)
    
    if result:
        print("❌ 不应该触发压缩！")
    else:
        print("✅ 未触发压缩 (符合预期)")


def test_recent_messages_ok_compress_history():
    """测试场景 1: 最近消息正常，但总量超限，压缩历史消息"""
    print_separator("测试场景 1: 最近消息正常，压缩历史消息")
    
    model = create_qwen_model()
    context_manager = ContextManagerMiddleware(
        model=model,
        max_token_ratio=0.8,
        single_msg_ratio=0.8
    )
    
    print(f"Token 限制: {context_manager.max_context_tokens}")
    
    # 创建多轮对话，让总量超出限制，但最近一轮正常
    # 目标：前面几轮加起来超过限制的一半，最近一轮很短
    history_tokens = int(context_manager.max_context_tokens * 0.7)
    
    messages = [
        SystemMessage(content="你是一个有帮助的助手"),
        HumanMessage(content=create_long_content("历史问题1：", history_tokens // 6)),
        AIMessage(content=create_long_content("历史回答1：", history_tokens // 6)),
        HumanMessage(content=create_long_content("历史问题2：", history_tokens // 6)),
        AIMessage(content=create_long_content("历史回答2：", history_tokens // 6)),
        HumanMessage(content=create_long_content("历史问题3：", history_tokens // 6)),
        AIMessage(content=create_long_content("历史回答3：", history_tokens // 6)),
        HumanMessage(content="最新问题：这是一个简短的问题"),
        AIMessage(content="最新回答：这是一个简短的回答"),
    ]
    
    total_tokens = count_tokens_approximately(messages)
    last_human_idx = 7  # 倒数第二条消息
    recent_tokens = count_tokens_approximately(messages[last_human_idx:])
    
    print(f"压缩前总 token 数: {total_tokens}")
    print(f"最近消息 token 数: {recent_tokens}")
    print(f"是否应触发压缩: {total_tokens > context_manager.max_context_tokens}")
    print(f"最近消息是否超限: {recent_tokens > context_manager.max_context_tokens}")
    
    state = {"messages": messages}
    result = context_manager.before_model(state, None)
    
    if result:
        # 过滤掉 RemoveMessage
        compressed_messages = [m for m in result["messages"] if not isinstance(m, RemoveMessage)]
        print("\n✅ 触发压缩")
        print(f"压缩后消息数量: {len(compressed_messages)}")
        print(f"压缩后 token 数: {count_tokens_approximately(compressed_messages)}")
        
        # 查找归档通知
        for msg in compressed_messages:
            if isinstance(msg, HumanMessage) and "[系统]" in msg.content:
                print(f"\n归档通知预览:\n{msg.content[:400]}...")
                break
        
        # 验证最近的消息是否保留
        has_recent = any("最新问题" in str(m.content) for m in compressed_messages)
        print(f"\n最近消息是否保留: {'✅ 是' if has_recent else '❌ 否'}")
    else:
        print("❌ 未触发压缩 (不符合预期)")


def test_recent_messages_exceed_compress_old():
    """测试场景 2: 最近消息本身就超限，压缩所有旧消息"""
    print_separator("测试场景 2: 最近消息超限，压缩所有旧消息")
    
    model = create_qwen_model()
    context_manager = ContextManagerMiddleware(
        model=model,
        max_token_ratio=0.8,
        single_msg_ratio=0.8
    )
    
    print(f"Token 限制: {context_manager.max_context_tokens}")
    
    # 创建一个超长的最新消息，让它自己就超出限制
    recent_tokens = int(context_manager.max_context_tokens * 1.1)  # 超出10%
    
    messages = [
        SystemMessage(content="你是一个有帮助的助手"),
        HumanMessage(content="旧问题1：这是一个普通的问题"),
        AIMessage(content="旧回答1：这是一个普通的回答"),
        HumanMessage(content="旧问题2：这是另一个问题"),
        AIMessage(content="旧回答2：这是另一个回答"),
        HumanMessage(content=create_long_content("最新超长问题：", recent_tokens)),
        AIMessage(content="针对超长问题的简短回答"),
    ]
    
    total_tokens = count_tokens_approximately(messages)
    last_human_idx = 5
    recent_msg_tokens = count_tokens_approximately(messages[last_human_idx:])
    system_tokens = count_tokens_approximately([messages[0]])
    recent_with_system = recent_msg_tokens + system_tokens
    
    print(f"压缩前总 token 数: {total_tokens}")
    print(f"最近消息 token 数: {recent_msg_tokens}")
    print(f"最近消息 + SystemMessage: {recent_with_system}")
    print(f"是否应触发压缩: {total_tokens > context_manager.max_context_tokens}")
    print(f"最近消息是否超限: {recent_with_system > context_manager.max_context_tokens}")
    
    state = {"messages": messages}
    result = context_manager.before_model(state, None)
    
    if result:
        # 过滤掉 RemoveMessage
        compressed_messages = [m for m in result["messages"] if not isinstance(m, RemoveMessage)]
        print("\n✅ 触发压缩")
        print(f"压缩后消息数量: {len(compressed_messages)}")
        print(f"压缩后 token 数: {count_tokens_approximately(compressed_messages)}")
        
        # 查找归档通知
        for msg in compressed_messages:
            if isinstance(msg, HumanMessage) and "[系统]" in msg.content:
                print(f"\n归档通知预览:\n{msg.content[:400]}...")
                break
        
        # 验证旧消息是否被压缩
        has_old = any("旧问题" in str(m.content) for m in compressed_messages if "[系统]" not in str(m.content))
        has_recent = any("最新超长问题" in str(m.content) for m in compressed_messages)
        print(f"\n旧消息是否保留: {'❌ 是 (不应保留)' if has_old else '✅ 否 (已压缩)'}")
        print(f"最近消息是否保留: {'✅ 是' if has_recent else '❌ 否'}")
    else:
        print("❌ 未触发压缩 (不符合预期)")


def test_single_message_offload():
    """测试场景 3: 单条消息过大，触发卸载到文件"""
    print_separator("测试场景 3: 单条消息过大，卸载到文件")
    
    model = create_qwen_model()
    context_manager = ContextManagerMiddleware(
        model=model,
        max_token_ratio=0.8,
        single_msg_ratio=0.8
    )
    
    print(f"单条消息限制: {context_manager.single_msg_limit}")
    
    # 创建一个超过单条消息限制的消息
    huge_content = create_long_content("超大消息内容：", context_manager.single_msg_limit + 1000)
    
    messages = [
        SystemMessage(content="你是一个有帮助的助手"),
        HumanMessage(content=huge_content),
        AIMessage(content="我已处理了你的消息"),
    ]
    
    msg_tokens = count_tokens_approximately([messages[1]])
    print(f"超大消息 token 数: {msg_tokens}")
    print(f"是否超过限制: {msg_tokens > context_manager.single_msg_limit}")
    
    state = {"messages": messages}
    result = context_manager.before_model(state, None)
    
    if result:
        processed_messages = [m for m in result["messages"] if not isinstance(m, RemoveMessage)]
        print("\n✅ 触发处理")
        
        # 检查是否有消息被替换为文件引用
        for msg in processed_messages:
            if isinstance(msg, HumanMessage) and "系统提示" in msg.content and "已保存至" in msg.content:
                print("\n消息已卸载到文件")
                print(f"预览:\n{msg.content[:500]}...")
                break
    else:
        print("❌ 未触发处理 (不符合预期)")


def main():
    """运行所有测试"""
    print("\n" + "="*60)
    print("  Context Manager 压缩策略测试")
    print("="*60)
    
    try:
        # 运行测试
        test_no_compression()
        test_recent_messages_ok_compress_history()
        test_recent_messages_exceed_compress_old()
        test_single_message_offload()
        
        print_separator("✅ 所有测试完成")
        
    except Exception as e:
        print_separator("❌ 测试失败")
        print(f"错误: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()
