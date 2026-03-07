"""
测试 RAG 工具 (search_documents & search_task_experience)
"""
import os
from dotenv import load_dotenv
from tools.rag_tools import search_documents, search_task_experience

load_dotenv()
os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"


def test_search_documents():
    """测试搜索项目文档/技术文档"""
    print("=" * 80)
    print("测试 RAG 工具：search_documents")
    print("=" * 80)

    queries = [
        "如何使用 LangChain 进行 RAG 系统开发？",
        "Playwright 自动化浏览器操作",
        "完全不相关的随机查询内容xyz123",
    ]

    for idx, query in enumerate(queries, 1):
        print(f"\n【测试 {idx}】查询: {query}")
        print("-" * 80)
        result = search_documents.invoke({"query": query})
        print(result)

    print("\n" + "=" * 80)
    print("search_documents 测试完成")
    print("=" * 80)


def test_search_task_experience():
    """测试搜索历史任务执行经验"""
    print("=" * 80)
    print("测试 RAG 工具：search_task_experience")
    print("=" * 80)

    cases = [
        {"query": "如何登录网站", "task_type": "login"},
        {"query": "如何提取表格数据", "task_type": "data_extraction", "website": None},
        {"query": "完全不相关的随机查询内容xyz123", "task_type": None},
    ]

    for idx, case in enumerate(cases, 1):
        print(f"\n【测试 {idx}】查询: {case['query']}")
        print("-" * 80)
        result = search_task_experience.invoke({
            "query": case["query"],
            "task_type": case.get("task_type"),
            "website": case.get("website"),
        })
        print(result)

    print("\n" + "=" * 80)
    print("search_task_experience 测试完成")
    print("=" * 80)


def test_tool_schema():
    """测试工具的 schema 定义"""
    print("\n" + "=" * 80)
    print("工具 Schema 信息")
    print("=" * 80)

    for tool in [search_documents, search_task_experience]:
        print(f"工具名称: {tool.name}")
        print(f"工具描述: {tool.description}")
        print(f"工具参数: {tool.args}")
        print("-" * 80)

    print("=" * 80)


if __name__ == "__main__":
    try:
        # 测试工具 schema
        test_tool_schema()
        
        # 测试工具功能
        test_search_documents()
        test_search_task_experience()
        
    except Exception as e:
        print(f"\n❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()
