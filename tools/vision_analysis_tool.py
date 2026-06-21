import base64
import logging
import os
from typing import Any, Optional, Type

import httpx

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
    使用视觉模型分析图像的 LangChain 工具。

    默认保持 Qwen3-VL；当 VISION_PROVIDER=glm 或 LLM_PROVIDER=glm 时，
    使用 GLM OpenAI-compatible `/chat/completions` 视觉接口。
    """

    name: str = "vl_analysis_tool"
    description: str = (
        "适用于详细描述图像、识别物体、分析场景、解读图表等视觉任务。"
        "输入需要一个有效的图像文件路径和分析提示词。"
    )
    args_schema: Type[BaseModel] = ImageAnalysisInput

    model_name: str = "qwen3-vl-plus"
    _model = None

    @property
    def vision_provider(self) -> str:
        return (os.getenv("VISION_PROVIDER") or os.getenv("LLM_PROVIDER") or "qwen").strip().lower()

    @property
    def active_model_name(self) -> str:
        if self.vision_provider == "glm":
            return (os.getenv("VISION_MODEL") or os.getenv("GLM_MODEL") or "glm-5").strip()
        return (os.getenv("VISION_MODEL") or self.model_name).strip()

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

    @property
    def model(self):
        if self._model is None:
            self._initialize_model()
        return self._model

    def _initialize_model(self):
        self._model = create_qwen_model(
            model_name=self.active_model_name,
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

    @staticmethod
    def _build_data_url(image_path: str) -> str:
        suffix = os.path.splitext(image_path)[1].lower()
        mime_type = {
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".png": "image/png",
            ".webp": "image/webp",
            ".gif": "image/gif",
        }.get(suffix, "image/png")
        with open(image_path, "rb") as img:
            encoded = base64.b64encode(img.read()).decode("utf-8")
        return f"data:{mime_type};base64,{encoded}"

    def _build_glm_payload(self, image_path: str, prompt: str) -> dict[str, Any]:
        return {
            "model": self.active_model_name,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": self._build_model_prompt(prompt)},
                        {"type": "image_url", "image_url": {"url": self._build_data_url(image_path)}},
                    ],
                }
            ],
            "temperature": 0,
        }

    @staticmethod
    def _extract_glm_text(data: dict[str, Any]) -> str:
        choices = data.get("choices") or []
        if not choices:
            return "无法识别验证码，GLM 未返回候选结果"
        content = (choices[0].get("message") or {}).get("content")
        if isinstance(content, str):
            return content.strip() or "无法识别验证码，GLM 返回为空"
        if isinstance(content, list):
            text = "\n".join(
                item.get("text", "")
                for item in content
                if isinstance(item, dict) and item.get("type") == "text"
            ).strip()
            return text or "无法识别验证码，GLM 返回为空"
        return str(content) if content else "无法识别验证码，GLM 返回为空"

    def _glm_endpoint(self) -> str:
        base_url = (os.getenv("GLM_BASE_URL") or "https://api.z.ai/api/paas/v4").rstrip("/")
        return base_url if base_url.endswith("/chat/completions") else f"{base_url}/chat/completions"

    def _run_glm(self, image_path: str, prompt: str) -> str:
        api_key = (os.getenv("GLM_API_KEY") or "").strip()
        if not api_key:
            return "分析图像时出错: VISION_PROVIDER=glm 但 GLM_API_KEY 为空。"
        with httpx.Client(timeout=httpx.Timeout(120.0, connect=30.0)) as client:
            response = client.post(
                self._glm_endpoint(),
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json=self._build_glm_payload(image_path, prompt),
            )
            response.raise_for_status()
            return self._extract_glm_text(response.json())

    async def _arun_glm(self, image_path: str, prompt: str) -> str:
        api_key = (os.getenv("GLM_API_KEY") or "").strip()
        if not api_key:
            return "分析图像时出错: VISION_PROVIDER=glm 但 GLM_API_KEY 为空。"
        async with httpx.AsyncClient(timeout=httpx.Timeout(120.0, connect=30.0)) as client:
            response = await client.post(
                self._glm_endpoint(),
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json=self._build_glm_payload(image_path, prompt),
            )
            response.raise_for_status()
            return self._extract_glm_text(response.json())

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
            if self.vision_provider == "glm":
                return self._run_glm(image_path, prompt)

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
                response = self.model.invoke([message])
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
            if self.vision_provider == "glm":
                return await self._arun_glm(image_path, prompt)

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
                response = await self.model.ainvoke([message])
                return self._extract_text_result(response)
        except Exception as e:
            return f"分析图像时出错: {str(e)}"
