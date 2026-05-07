import base64
import logging
import os
from typing import Any, Optional, Type

from langchain_core.callbacks import (
    AsyncCallbackManagerForToolRun,
    CallbackManagerForToolRun,
)
from langchain_core.messages import HumanMessage
from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field

from utils.qwen_model import create_qwen_model

logger = logging.getLogger(__name__)


class ImageAnalysisInput(BaseModel):
    """图像分析工具的输入参数"""

    image_path: str = Field(description="要分析的图像文件的绝对路径")
    prompt: str = Field(description="指导模型如何分析图像的提示词", default="详细描述这张图片的内容")


class VLAnalysisTool(BaseTool):
    """
    使用 Qwen3-VL 多模态模型分析图像的 LangChain 工具。
    """

    name: str = "vl_analysis_tool"
    description: str = (
        "适用于详细描述图像、识别物体、分析场景、解读图表等视觉任务。"
        "输入需要一个有效的图像文件路径和分析提示词。"
    )
    args_schema: Type[BaseModel] = ImageAnalysisInput

    model_name: str = "qwen3-vl-plus"
    _model = None

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._initialize_model()

    def _initialize_model(self):
        self._model = create_qwen_model(
            model_name=self.model_name,
        )

    @staticmethod
    def _build_model_prompt(prompt: str) -> str:
        return f"请根据以下图片内容，{prompt}"

    @staticmethod
    def _extract_text_result(response: Any) -> str:
        if not response or not response.content:
            return "无法识别验证码，模型未返回结果"

        result = response.content
        if isinstance(result, list) and len(result) > 0:
            if isinstance(result[0], dict) and "text" in result[0]:
                result = result[0]["text"]
            else:
                result = str(result[0])

        return str(result) if result else "无法识别验证码，请手动输入"

    def _run(
        self,
        image_path: str,
        prompt: str = "详细描述这张图片的内容",
        run_manager: Optional[CallbackManagerForToolRun] = None,
        **kwargs: Any,
    ) -> str:
        if not os.path.exists(image_path):
            return f"错误：图像文件不存在于路径 {image_path}。请提供有效的图像路径。"

        try:
            logger.debug(
                "vl_analysis_tool sync call: image_path=%s prompt=%r",
                image_path,
                prompt,
            )
            with open(image_path, "rb") as img:
                imgbase64 = base64.b64encode(img.read()).decode("utf-8")
                model_prompt = self._build_model_prompt(prompt)
                logger.debug(
                    "vl_analysis_tool sync model prompt preview: %r",
                    model_prompt[:500],
                )
                message = HumanMessage(
                    content=model_prompt,
                    content_blocks=[
                        {"type": "image", "image": f"data:image/png;base64,{imgbase64}"}
                    ],
                )
                response = self._model.invoke([message])
                return self._extract_text_result(response)
        except Exception as e:
            return f"分析图像时出错: {str(e)}"

    async def _arun(
        self,
        image_path: str,
        prompt: str = "详细描述这张图片的内容",
        run_manager: Optional[AsyncCallbackManagerForToolRun] = None,
        **kwargs: Any,
    ) -> str:
        if not os.path.exists(image_path):
            return f"错误：图像文件不存在于路径 {image_path}。请提供有效的图像路径。"

        try:
            logger.debug(
                "vl_analysis_tool async call: image_path=%s prompt=%r",
                image_path,
                prompt,
            )
            with open(image_path, "rb") as img:
                imgbase64 = base64.b64encode(img.read()).decode("utf-8")
                model_prompt = self._build_model_prompt(prompt)
                logger.debug(
                    "vl_analysis_tool async model prompt preview: %r",
                    model_prompt[:500],
                )
                message = HumanMessage(
                    content=model_prompt,
                    content_blocks=[
                        {"type": "image", "image": f"data:image/png;base64,{imgbase64}"}
                    ],
                )
                response = await self._model.ainvoke([message])
                return self._extract_text_result(response)
        except Exception as e:
            return f"分析图像时出错: {str(e)}"
