"""
经验系统测试脚本
测试链路记录、经验总结、经验检索的完整流程
"""
from sqlalchemy.orm import Session

from entity import AgentTrace, Experience
from database import engine
from rag.experience_rag import search_experience, format_experiences_for_prompt


def test_database_tables():
    """测试数据库表是否正确创建"""
    print("\n" + "=" * 80)
    print("测试 1：验证数据库表结构")
    print("=" * 80)
    
    with Session(engine) as session:
        # 检查 AgentTrace 表的新字段
        trace_count = session.query(AgentTrace).count()
        print(f"✅ AgentTrace 表可访问，当前记录数：{trace_count}")
        
        if trace_count > 0:
            latest_trace = session.query(AgentTrace).order_by(
                AgentTrace.created_at.desc()
            ).first()
            print(f"   最新记录 session_id: {latest_trace.session_id}")
            print(f"   turn_number: {latest_trace.turn_number}")
            print(f"   last_message_count: {latest_trace.last_message_count}")
        
        # 检查 Experience 表
        exp_count = session.query(Experience).count()
        print(f"✅ Experience 表可访问，当前记录数：{exp_count}")
        
        if exp_count > 0:
            latest_exp = session.query(Experience).order_by(
                Experience.created_at.desc()
            ).first()
            print(f"   最新经验类型: {latest_exp.task_type}")
            print(f"   任务描述: {latest_exp.task_description[:50]}...")


def test_experience_search():
    """测试经验检索功能"""
    print("\n" + "=" * 80)
    print("测试 2：经验检索功能")
    print("=" * 80)
    
    # 测试查询
    test_queries = [
        "如何登录网站",
        "填写表单",
        "搜索商品"
    ]
    
    for query in test_queries:
        print(f"\n查询：{query}")
        experiences = search_experience(query, top_k=2)
        
        if experiences:
            print(f"✅ 找到 {len(experiences)} 条相关经验")
            for i, exp in enumerate(experiences, 1):
                print(f"  {i}. [{exp.task_type}] {exp.task_description[:40]}...")
        else:
            print("⚠️  未找到相关经验")


def test_format_experiences():
    """测试经验格式化功能"""
    print("\n" + "=" * 80)
    print("测试 3：经验格式化")
    print("=" * 80)
    
    experiences = search_experience("登录", top_k=1)
    
    if experiences:
        formatted = format_experiences_for_prompt(experiences)
        print("✅ 格式化结果：")
        print(formatted[:500] + "..." if len(formatted) > 500 else formatted)
    else:
        print("⚠️  没有经验可供格式化")


def test_session_management():
    """测试多轮对话的 session 管理（追加更新模式）"""
    print("\n" + "=" * 80)
    print("测试 4：Session 管理（追加更新模式）")
    print("=" * 80)
    
    with Session(engine) as session:
        # 查找有多轮对话的 session
        multi_turn_traces = session.query(AgentTrace).filter(
            AgentTrace.turn_number > 1
        ).all()
        
        if multi_turn_traces:
            print(f"✅ 找到 {len(multi_turn_traces)} 条多轮对话记录")
            for trace in multi_turn_traces[:3]:
                print(f"  Session: {trace.session_id[:8]}..., "
                      f"Turn: {trace.turn_number}, "
                      f"Query: {trace.user_query[:30]}...")
        else:
            print("⚠️  暂无多轮对话记录（所有任务都是单轮完成）")
        
        # 检查追加更新模式：同一 session 应该有多条记录
        from sqlalchemy import func
        multi_records = session.query(
            AgentTrace.session_id, 
            func.count(AgentTrace.id).label('count')
        ).group_by(AgentTrace.session_id).having(func.count(AgentTrace.id) > 1).all()
        
        if multi_records:
            print(f"\n✅ 追加更新模式正常：{len(multi_records)} 个 session 有多条记录")
            for sid, count in multi_records[:3]:
                print(f"  Session {sid[:8]}... 有 {count} 轮对话")
                # 验证 turn_number 是否连续
                traces = session.query(AgentTrace).filter_by(
                    session_id=sid
                ).order_by(AgentTrace.turn_number).all()
                turn_numbers = [t.turn_number for t in traces]
                if turn_numbers == list(range(1, count + 1)):
                    print(f"    ✓ Turn 编号连续：{turn_numbers}")
                else:
                    print(f"    ⚠️  Turn 编号不连续：{turn_numbers}")
        else:
            print("⚠️  所有 session 只有一条记录（可能还没有多轮对话）")


def test_experience_statistics():
    """测试经验统计信息"""
    print("\n" + "=" * 80)
    print("测试 5：经验统计")
    print("=" * 80)
    
    with Session(engine) as session:
        from sqlalchemy import func
        
        # 按任务类型统计
        stats = session.query(
            Experience.task_type,
            func.count(Experience.id).label('count')
        ).group_by(Experience.task_type).all()
        
        if stats:
            print("✅ 按任务类型统计：")
            for task_type, count in stats:
                print(f"  {task_type}: {count} 条")
        else:
            print("⚠️  暂无经验数据")
        
        # 成功率统计
        total = session.query(Experience).count()
        success = session.query(Experience).filter(Experience.success).count()
        
        if total > 0:
            print(f"\n✅ 总经验数：{total}")
            print(f"   成功：{success} ({success/total*100:.1f}%)")
            print(f"   失败：{total-success} ({(total-success)/total*100:.1f}%)")


if __name__ == "__main__":
    print("=" * 80)
    print("经验系统测试套件")
    print("=" * 80)
    
    try:
        test_database_tables()
        test_experience_search()
        test_format_experiences()
        test_session_management()
        test_experience_statistics()
        
        print("\n" + "=" * 80)
        print("✨ 所有测试完成！")
        print("=" * 80)
    except Exception as e:
        print(f"\n❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()
