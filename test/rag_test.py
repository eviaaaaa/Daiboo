"""
测试 RAG 工具 (search_knowledge_base)
"""
import os
from dotenv import load_dotenv
from tools.rag_tools import search_knowledge_base

load_dotenv()
os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"


def test_search_knowledge_base():
    """
    测试搜索知识库工具
    """
    print("=" * 80)
    print("测试 RAG 工具：search_knowledge_base")
    print("=" * 80)
    
    # 测试查询 1
    query1 = "如何使用 LangChain 进行 RAG 系统开发？"
    print(f"\n【测试 1】查询: {query1}")
    print("-" * 80)
    
    result1 = search_knowledge_base.invoke({"query": query1})
    print(result1)
    
    # 测试查询 2
    query2 = "如何使用 Playwright 自动化浏览器操作？"
    print(f"\n{'=' * 80}")
    print(f"【测试 2】查询: {query2}")
    print("-" * 80)
    
    result2 = search_knowledge_base.invoke({"query": query2})
    print(result2)
    
    # 测试查询 3：测试没有结果的情况
    query3 = "完全不相关的随机查询内容xyz123"
    print(f"\n{'=' * 80}")
    print(f"【测试 3】查询: {query3}")
    print("-" * 80)
    
    result3 = search_knowledge_base.invoke({"query": query3})
    print(result3)
    
    print("\n" + "=" * 80)
    print("测试完成")
    print("=" * 80)


def test_tool_schema():
    """
    测试工具的 schema 定义
    """
    print("\n" + "=" * 80)
    print("工具 Schema 信息")
    print("=" * 80)
    
    print(f"工具名称: {search_knowledge_base.name}")
    print(f"工具描述: {search_knowledge_base.description}")
    print(f"工具参数: {search_knowledge_base.args}")
    print("=" * 80)


if __name__ == "__main__":
    try:
        # 测试工具 schema
        test_tool_schema()
        
        # 测试工具功能
        test_search_knowledge_base()
        
    except Exception as e:
        print(f"\n❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()
