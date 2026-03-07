"""
测试 VLAnalysisTool 工具是否可用
"""
import asyncio
from pathlib import Path
from dotenv import load_dotenv
import pytest
from utils import MyVcr
from tools import VLAnalysisTool

load_dotenv()
CORREND_CODE = "1jiv"

@MyVcr.use_cassette('test/vcr_cassettes/test_vl_tool_async.yaml')
async def test_vl_tool():
    """异步测试 VLAnalysisTool"""
    print("=" * 60)
    print("测试 VLAnalysisTool 工具")
    print("=" * 60)
    
    # 创建工具实例
    tool = VLAnalysisTool()
    print(f"✅ 工具名称: {tool.name}")
    print(f"✅ 工具描述: {tool.description}")
    print()
    
    # 测试图片路径
    image_path = os.getenv("TEST_VL_IMAGE_PATH", "test_fixtures/sample.png")
    path = Path(image_path)
    
    # 验证文件存在
    if not path.exists():
        print(f"❌ 错误：图片文件不存在：{image_path}")
        return
    
    print(f"✅ 图片文件存在：{image_path}")

    print(f"   文件大小: {path.stat().st_size} 字节")
    print()
    
    # 测试工具调用（异步）
    print("🔍 开始异步调用工具...")
    prompt = "识别这张验证码图片中的字符，只返回4位数字或字母，不要有其他说明"
    
    try:
        result: str = await tool._arun(
            image_path=image_path,
            prompt=prompt
        )
        print(f"\n✅ 工具执行成功！")
        assert(result.find(CORREND_CODE)), "识别结果中找到预期的验证码内容"
        print(f"📊 识别结果:\n{result}")
    except Exception as e:
        print(f"\n❌ 工具执行失败: {e}")
        import traceback
        traceback.print_exc()

@MyVcr.use_cassette('test/vcr_cassettes/test_vl_tool_sync.yaml')
def test_vl_tool_sync():
    """同步测试 VLAnalysisTool"""
    print("\n" + "=" * 60)
    print("测试同步调用")
    print("=" * 60)
    
    tool = VLAnalysisTool()
    image_path = os.getenv("TEST_VL_IMAGE_PATH", "test_fixtures/sample.png")
    
    if not Path(image_path).exists():
        print(f"❌ 错误：图片文件不存在：{image_path}")
        return
    
    print("🔍 开始同步调用工具...")
    prompt = "识别这张验证码图片中的字符，只返回4位数字或字母"
    
    try:
        result = tool._run(
            image_path=image_path,
            prompt=prompt
        )
        assert(result.find(CORREND_CODE)), "识别结果中找到预期的验证码内容"
        print(f"\n✅ 工具执行成功！")
        print(f"📊 识别结果:\n{result}")
    except Exception as e:
        print(f"\n❌ 工具执行失败: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    # 测试异步调用
    asyncio.run(test_vl_tool())
    # 测试同步调用
    test_vl_tool_sync()



