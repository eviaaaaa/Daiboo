import base64
import os
from typing import Any, Optional, Type
from pydantic import BaseModel, Field
from langchain_core.tools import BaseTool
from langchain_core.messages import HumanMessage
from langchain_community.chat_models.tongyi import ChatTongyi
from langchain_core.callbacks import (
    AsyncCallbackManagerForToolRun,
    CallbackManagerForToolRun,
)

class ImageAnalysisInput(BaseModel):
    """图像分析工具的输入参数"""
    image_path: str = Field(description="要分析的图像文件的对绝路径")
    prompt: str = Field(description="指导模型如何分析图像的提示词", default="详细描述这张图片的内容")

class VLAnalysisTool(BaseTool):
    """
    使用Qwen3-VL多模态模型分析图像的LangChain工具
    """
    name: str = "vl_analysis_tool"
    description: str = (
        "适用于详细描述图像、识别物体、分析场景、解读图表等视觉任务。"
        "输入需要一个有效的图像文件路径和分析提示词。"
    )
    args_schema: Type[BaseModel] = ImageAnalysisInput
    
    # 工具配置参数
    model_name: str = "qwen3-vl-plus"
    
    _model = None  # 私有模型实例
    
    def __init__(self, **kwargs):
        """初始化图像分析工具"""
        super().__init__(**kwargs)
        self._initialize_model()
    
    def _initialize_model(self):
        """初始化Qwen-VL模型"""
        # 优先使用提供的API密钥，否则从环境变量获取
        
        self._model = ChatTongyi(
            model_name=self.model_name,
        )
    
    def _run(
        self,
        image_path: str,
        prompt: str = "详细描述这张图片的内容",
        run_manager: Optional[CallbackManagerForToolRun] = None,
        **kwargs: Any
    ) -> str:
        """
        执行图像分析
        
        Args:
            image_path: 图像文件路径
            prompt: 分析提示词
            **kwargs: 额外参数
            
        Returns:
            模型生成的分析结果
        """
        # 验证图像文件是否存在
        if not os.path.exists(image_path):
            return f"错误：图像文件不存在于路径 {image_path}。请提供有效的图像路径。"
        
        try:
            with open(image_path, "rb") as img:
                imgbase64 = base64.b64encode(img.read()).decode('utf-8')  # 修复：需要调用 .read()
                # imgBlock:ImageContentBlock = create_image_block(base64=imgbase64,mime_type="image/png")
                # 构建多模态消息
                message = HumanMessage(
                    content=f"请根据以下图片内容，{prompt}",
                    content_blocks=[
                        {"type":"image","image":f"data:image/png;base64,{imgbase64}"}
                    ]
                )
                
                # 调用模型
                response = self._model.invoke([message])
                
                # 返回结果 - 确保不返回None
                if not response or not response.content:
                    return "无法识别验证码，模型未返回结果"
                
                result = response.content
                
                # 处理返回结果格式（可能是列表或字符串）
                if isinstance(result, list) and len(result) > 0:
                    if isinstance(result[0], dict) and 'text' in result[0]:
                        result = result[0]['text']
                    else:
                        result = str(result[0])
                
                return str(result) if result else "无法识别验证码，请手动输入"
        except Exception as e:
            return f"分析图像时出错: {str(e)}"
    
    async def _arun(
        self,
        image_path: str,
        prompt: str = "详细描述这张图片的内容",
        run_manager: Optional[AsyncCallbackManagerForToolRun] = None,

        **kwargs: Any
    ) -> str:
        """异步执行图像分析"""
        # 验证图像文件是否存在
        if not os.path.exists(image_path):
            return f"错误：图像文件不存在于路径 {image_path}。请提供有效的图像路径。"
        
        try:
            with open(image_path, "rb") as img:
                imgbase64 = base64.b64encode(img.read()).decode('utf-8')  # 修复：需要调用 .read()
                # imgBlock:ImageContentBlock = create_image_block(base64=imgbase64,mime_type="image/png")
                # 构建多模态消息
                message = HumanMessage(
                    content=f"请根据以下图片内容，{prompt}",
                    content_blocks=[
                        {"type":"image","image":f"data:image/png;base64,{imgbase64}"}
                    ]
                )
                
                # 调用模型
                response = await self._model.ainvoke([message])
                
                # 返回结果 - 确保不返回None
                if not response or not response.content:
                    return "无法识别验证码，模型未返回结果"
                
                result = response.content
                
                # 处理返回结果格式（可能是列表或字符串）
                if isinstance(result, list) and len(result) > 0:
                    if isinstance(result[0], dict) and 'text' in result[0]:
                        result = result[0]['text']
                    else:
                        result = str(result[0])
                
                return str(result) if result else "无法识别验证码，请手动输入"
            
        except Exception as e:
            return f"分析图像时出错: {str(e)}"

