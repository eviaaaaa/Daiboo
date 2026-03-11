from typing import Optional, Dict, Any, Literal, Type
import os
from datetime import datetime
from pathlib import Path
from PIL import Image, ImageDraw
import logging

from playwright.async_api import Page as AsyncPage, TimeoutError as AsyncPlaywrightTimeoutError
from langchain_core.callbacks import AsyncCallbackManagerForToolRun, CallbackManagerForToolRun
from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field, ConfigDict


# 配置日志
logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

# 默认截图保存目录
DEFAULT_SCREENSHOT_DIR = Path.home() / "tool_screenshots"


class CaptureElementContextToolInput(BaseModel):
    """CaptureElementContextTool 的输入参数模型"""
    model_config = ConfigDict(extra="forbid")  # 严格模式：禁止额外参数
    
    element_description: str = Field(
        ...,
        description=(
            "要捕获的元素的描述。支持以下格式：\n"
            "1. CSS选择器：'#elementId'、'.className'、'tag#id'（如 'img#SafeCodeImg'）\n"
            "2. 文本描述：'登录按钮'、'验证码图片'\n"
            "3. ID描述：'验证码图片，id为SafeCodeImg'\n"
            "优先使用CSS选择器以确保准确定位。"
        )
    )
    
    context_size: Literal["small", "medium", "large"] = Field(
        default="medium",
        description="要包含的周围上下文的大小。small（30%边距），medium（50%边距），large（80%边距）。"
    )
    
    include_surrounding_text: bool = Field(
        default=True,
        description="是否提取元素周围的文本内容作为额外的上下文。"
    )
    
    screenshot_dir: Optional[str] = Field(
        default=None,
        description=f"截图保存的目录路径。如果未指定，将使用默认目录: {DEFAULT_SCREENSHOT_DIR}"
    )


class CaptureElementContextTool(BaseTool):
    name: str = "capture_element_context"
    description: str = (
        "捕获特定元素及其周围上下文的截图并保存到本地文件系统。"
        "返回截图文件的绝对路径。当您需要查看页面上的某个元素以了解其状态、位置或周围的UI元素时，请使用此功能。"
    )

    # 参数 schema 定义
    args_schema: Type[BaseModel] = CaptureElementContextToolInput

    # ScreenshotHelper 实例（通过共享 CDP 连接获取页面）
    helper: Any = Field(default=None, exclude=True)

    default_screenshot_dir: Path = Field(default_factory=lambda: Path.home() / "tool_screenshots")
    
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        # 确保截图目录存在
        self.default_screenshot_dir = Path(DEFAULT_SCREENSHOT_DIR)
        self.default_screenshot_dir.mkdir(parents=True, exist_ok=True)
        logger.info(f"截图默认保存目录: {self.default_screenshot_dir}")

    def _get_screenshot_path(self, element_description: str, screenshot_dir: Optional[str] = None) -> Path:
        """生成唯一的截图文件路径"""
        # 确定保存目录
        save_dir = Path(screenshot_dir) if screenshot_dir else self.default_screenshot_dir
        save_dir.mkdir(parents=True, exist_ok=True)
        
        # 清理文件名中的特殊字符
        safe_name = "".join(c for c in element_description if c.isalnum() or c in (" ", "_", "-")).strip()
        safe_name = safe_name.replace(" ", "_")[:50]  # 限制长度
        
        # 生成带时间戳的唯一文件名
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:19]
        filename = f"{safe_name}_{timestamp}.png"
        
        return save_dir / filename

    async def _locate_element(self, page: AsyncPage, element_description: str) -> Any:
        """根据提供的描述智能定位元素，尝试多种策略确保定位成功"""
        import re
        
        # 策略0：优先处理明确的CSS选择器（以 # 或 . 开头）
        if element_description.startswith(("#", ".")):
            try:
                locator = page.locator(element_description)
                if await locator.count() > 0:
                    logger.info(f"✅ [策略0-CSS] 通过CSS选择器定位到元素: {element_description}")
                    return locator
            except Exception as e:
                logger.warning(f"⚠️ [策略0-CSS] CSS选择器失败: {e}")
        
        # 策略1：检查标签+ID组合（如 "img#SafeCodeImg"、"div.class"）
        if re.match(r'^[a-z]+[#.][a-zA-Z0-9_-]+$', element_description, re.IGNORECASE):
            try:
                locator = page.locator(element_description)
                if await locator.count() > 0:
                    logger.info(f"✅ [策略1-标签选择器] 定位到元素: {element_description}")
                    return locator
            except Exception as e:
                logger.warning(f"⚠️ [策略1-标签选择器] 失败: {e}")
        
        # 策略2：提取ID（如 "id为SafeCodeImg" 或 "验证码图片，ID=SafeCodeImg"）
        if "id" in element_description.lower():
            match = re.search(r'(?:id[为:=\s]*)?([a-zA-Z][a-zA-Z0-9_-]*)', element_description, re.IGNORECASE)
            if match:
                id_match = match.group(1)
                try:
                    locator = page.locator(f"#{id_match}")
                    if await locator.count() > 0:
                        logger.info(f"✅ [策略2-ID提取] 通过提取的ID定位到元素: #{id_match}")
                        return locator
                except Exception as e:
                    logger.warning(f"⚠️ [策略2-ID提取] 使用ID定位失败: {e}")
        
        # 策略3：尝试作为通用 CSS 选择器
        try:
            locator = page.locator(element_description)
            if await locator.count() > 0:
                logger.info(f"✅ [策略3-通用CSS] 定位到元素: {element_description}")
                return locator
        except Exception as e:
            logger.warning(f"⚠️ [策略3-通用CSS] 尝试CSS选择器失败: {e}")
        
        # 策略4：尝试通过文本内容获取（不区分大小写，部分匹配）
        try:
            locator = page.get_by_text(element_description, exact=False)
            if await locator.count() > 0:
                logger.info("✅ [策略4-文本匹配] 通过文本定位到元素")
                return locator
        except Exception as e:
            logger.warning(f"⚠️ [策略4-文本匹配] 失败: {e}")
        
        # 策略5：尝试通过角色和名称
        try:
            # 尝试常见的交互元素（添加 img 用于图片定位）
            for role in ["button", "link", "textbox", "checkbox", "radio", "img"]:
                try:
                    locator = page.get_by_role(role, name=element_description, exact=False)
                    if await locator.count() > 0:
                        logger.info(f"✅ [策略5-角色匹配] 通过角色'{role}'定位到元素")
                        return locator
                except Exception:
                    pass
        except Exception as e:
            logger.warning(f"⚠️ [策略5-角色匹配] 失败: {e}")
        
        # 策略6：回退到在可见元素中搜索文本内容
        try:
            elements = await page.evaluate("""
                (searchText) => {
                    // 获取所有具有文本内容或属性的可见元素
                    const elements = Array.from(document.querySelectorAll('*')).filter(el => {
                        const rect = el.getBoundingClientRect();
                        const style = window.getComputedStyle(el);
                        
                        // 检查元素是否可见
                        const isVisible = (
                            rect.width > 0 && 
                            rect.height > 0 && 
                            style.visibility !== 'hidden' && 
                            style.display !== 'none' &&
                            parseFloat(style.opacity) > 0.1
                        );
                        
                        // 检查元素是否包含搜索文本（文本内容或其他属性）
                        const hasText = el.textContent && 
                                       el.textContent.toLowerCase().includes(searchText.toLowerCase());
                        const hasAlt = el.alt && el.alt.toLowerCase().includes(searchText.toLowerCase());
                        const hasTitle = el.title && el.title.toLowerCase().includes(searchText.toLowerCase());
                        const hasPlaceholder = el.placeholder && el.placeholder.toLowerCase().includes(searchText.toLowerCase());
                        
                        return isVisible && (hasText || hasAlt || hasTitle || hasPlaceholder);
                    });
                    
                    // 按相关性（文本匹配质量）对元素进行排序
                    return elements
                        .map(el => ({
                            text: el.textContent.trim().slice(0, 100),
                            tag: el.tagName.toLowerCase(),
                            id: el.id,
                            classes: el.className,
                            alt: el.alt || '',
                            title: el.title || '',
                            matchQuality: Math.min(
                                el.textContent.toLowerCase().indexOf(searchText.toLowerCase()),
                                (el.alt || el.title || el.placeholder || '').toLowerCase().indexOf(searchText.toLowerCase())
                            )
                        }))
                        .sort((a, b) => a.matchQuality - b.matchQuality)
                        .slice(0, 5); // 返回前5个匹配项
                }
            """, element_description)
            
            if elements and len(elements) > 0:
                # 使用最佳匹配
                best_match = elements[0]
                # 基于元素属性创建唯一选择器
                if best_match['id']:
                    return page.locator(f"#{best_match['id']}")
                elif best_match['classes']:
                    # 清理 classes 字符串
                    clean_classes = ' '.join(best_match['classes'].split())
                    try:
                        return page.locator(f"{best_match['tag']}.{clean_classes.replace(' ', '.')}")
                    except Exception:
                        return page.locator(f"{best_match['tag']}")
                else:
                    # 回退到标签选择
                    return page.locator(f"{best_match['tag']}")
        except Exception as e:
            logger.debug(f"策略4搜索失败: {str(e)}")
            pass
        
        raise ValueError(f"无法定位描述为 '{element_description}' 的元素。"
                         f"请尝试使用 CSS 选择器（如 '#elementId' 或 '.className'）或更具体的文本描述。")

    def _calculate_context_area(
        self,
        element_box: Dict[str, float],
        viewport_size: Dict[str, float],
        margin_ratio: float = 0.5,
        min_size: Optional[Dict[str, int]] = None,
        max_size: Optional[Dict[str, int]] = None
    ) -> Dict[str, int]:
        """计算包括元素和周围上下文的截图区域"""
        min_size = min_size or {"width": 600, "height": 400}
        max_size = max_size or {"width": 1920, "height": 1080}
        
        context_width = element_box["width"] * (1 + 2 * margin_ratio)
        context_height = element_box["height"] * (1 + 2 * margin_ratio)
        
        context_width = max(min_size["width"], min(max_size["width"], context_width))
        context_height = max(min_size["height"], min(max_size["height"], context_height))
        
        capture_x = element_box["x"] + element_box["width"] / 2 - context_width / 2
        capture_y = element_box["y"] + element_box["height"] / 2 - context_height / 2
        
        capture_x = max(0, min(capture_x, viewport_size["width"] - context_width))
        capture_y = max(0, min(capture_y, viewport_size["height"] - context_height))
        
        # 确保元素完全在截图区域内
        if capture_x > element_box["x"]:
            capture_x = max(0, element_box["x"] - (context_width - element_box["width"]) / 2)
        
        if capture_y > element_box["y"]:
            capture_y = max(0, element_box["y"] - (context_height - element_box["height"]) / 2)
        
        if capture_x + context_width < element_box["x"] + element_box["width"]:
            capture_x = min(viewport_size["width"] - context_width, 
                           element_box["x"] + element_box["width"] - (context_width - element_box["width"]) / 2)
        
        if capture_y + context_height < element_box["y"] + element_box["height"]:
            capture_y = min(viewport_size["height"] - context_height,
                           element_box["y"] + element_box["height"] - (context_height - element_box["height"]) / 2)
        
        return {
            "x": int(capture_x),
            "y": int(capture_y),
            "width": int(context_width),
            "height": int(context_height)
        }

    async def _extract_surrounding_text(self, page: AsyncPage, element: Any) -> str:
        """提取元素周围的文本内容"""
        try:
            return await page.evaluate("""
                (element) => {
                    function getCleanText(el) {
                        return el.textContent.trim()
                            .replace(/\\s+/g, ' ')
                            .slice(0, 200);
                    }
                    
                    if (!element) return "未找到元素";
                    
                    const elementText = getCleanText(element);
                    const parent = element.parentElement;
                    const parentText = parent ? getCleanText(parent) : "";
                    
                    const siblings = parent ? Array.from(parent.children) : [];
                    const visibleSiblings = siblings.filter(el => 
                        el !== element && 
                        el.offsetWidth > 0 && 
                        el.offsetHeight > 0 &&
                        getCleanText(el).length > 5
                    );
                    
                    const results = [];
                    
                    if (elementText) {
                        results.push(`元素文本: ${elementText}`);
                    }
                    
                    if (parentText && parentText !== elementText) {
                        results.push(`父级上下文: ${parentText}`);
                    }
                    
                    if (visibleSiblings.length > 0) {
                        results.push("附近元素:");
                        visibleSiblings.slice(0, 3).forEach((sib, i) => {
                            const text = getCleanText(sib);
                            if (text.length > 5) {
                                results.push(`- ${sib.tagName.toLowerCase()}: ${text}`);
                            }
                        });
                    }
                    
                    return results.join('\\n');
                }
            """, element)
        except Exception as e:
            return f"提取周围文本时出错: {str(e)}"

    def _run(self, **kwargs) -> str:
        raise NotImplementedError("此工具仅支持异步调用，请使用 _arun")

    async def _arun(
        self,
        *,
        element_description: str,
        context_size: Literal["small", "medium", "large"] = "medium",
        include_surrounding_text: bool = True,
        screenshot_dir: Optional[str] = None,
        run_manager: Optional[AsyncCallbackManagerForToolRun] = None,
        **kwargs,
    ) -> str:
        """异步执行该工具的方法"""
        if self.helper is None:
            raise ValueError(f"ScreenshotHelper 未提供给 {self.name}")

        try:
            # 通过共享 CDP 连接获取当前页面
            page = await self.helper.get_page()
            
            # 配置上下文参数
            context_config = {
                "small": {"margin": 0.3, "min_size": {"width": 400, "height": 300}},
                "medium": {"margin": 0.5, "min_size": {"width": 600, "height": 400}},
                "large": {"margin": 0.8, "min_size": {"width": 800, "height": 600}}
            }[context_size]
            
            # 1. 定位元素
            element = await self._locate_element(page, element_description)
            
            # 2. 滚动元素到视图中
            await element.scroll_into_view_if_needed()
            await page.wait_for_timeout(300)
            
            # 3. 获取元素边界框和视口尺寸
            bounding_box = await element.bounding_box()
            if page.viewport_size:
                viewport_size = {"width": page.viewport_size["width"], "height": page.viewport_size["height"]}
            else:
                viewport_size = await page.evaluate("() => ({width: window.innerWidth, height: window.innerHeight})")
            
            if not bounding_box:
                raise ValueError("无法获取元素边界框")
            
            # 4. 计算上下文区域
            capture_area = self._calculate_context_area(
                bounding_box,
                viewport_size,
                context_config["margin"],
                context_config["min_size"]
            )
            
            # 5. 生成截图路径
            screenshot_path = self._get_screenshot_path(element_description, screenshot_dir)
            
            # 6. 截取计算区域的截图
            try:
                await page.screenshot(
                    path=str(screenshot_path),
                    clip={
                        "x": capture_area["x"],
                        "y": capture_area["y"],
                        "width": capture_area["width"],
                        "height": capture_area["height"]
                    },
                    timeout=10000  # 10秒超时
                )
            except Exception as e:
                # 如果带 clip 的截图失败（例如区域超出视口），尝试截取全屏或报错
                logger.error(f"截图失败: {e}")
                raise e
            
            # 7. （可选）提取周围文本
            surrounding_text = ""
            if include_surrounding_text:
                surrounding_text = await self._extract_surrounding_text(page, element)
            
            # 8. 创建返回消息
            content = (
                f"元素 '{element_description}' 的截图已保存到本地文件系统。\n"
                f"文件路径: {screenshot_path.absolute()}\n"
                f"截取区域：{capture_area['width']}x{capture_area['height']} 位于 ({capture_area['x']}, {capture_area['y']})\n"
            )
            
            if surrounding_text:
                content += f"\n周围文本上下文：\n{surrounding_text}"
            
            # 9. 添加调试覆盖层（如果启用）
            if os.getenv("DEBUG_MODE", "false").lower() == "true":
                await self._add_debug_overlay_to_file(
                    screenshot_path, 
                    bounding_box, 
                    capture_area,
                    element_description
                )
            
            return content
            
        except AsyncPlaywrightTimeoutError as e:
            error_msg = f"捕获元素上下文超时：{str(e)}"
            logger.error(error_msg)
            return error_msg
        
        except Exception as e:
            error_msg = f"捕获元素上下文错误：{str(e)}"
            logger.exception(error_msg)
            return error_msg

    async def _add_debug_overlay_to_file(
        self,
        screenshot_path: Path,
        element_box: Dict[str, float],
        capture_area: Dict[str, int],
        element_description: str
    ):
        """异步版本：向截图文件添加调试覆盖层"""
        try:
            # 打开截图文件
            img = Image.open(screenshot_path)
            draw = ImageDraw.Draw(img)
            
            # 计算元素相对于截取区域的位置
            rel_x = element_box["x"] - capture_area["x"]
            rel_y = element_box["y"] - capture_area["y"]
            
            # 绘制元素边界框（红色）
            draw.rectangle(
                [rel_x, rel_y, rel_x + element_box["width"], rel_y + element_box["height"]],
                outline="red",
                width=3
            )
            
            # 添加元素描述标签
            self._draw_debug_text(draw, rel_x + 5, rel_y + 5, element_description, "red")
            
            # 绘制截取区域边框（蓝色）
            draw.rectangle(
                [0, 0, img.width - 1, img.height - 1],
                outline="blue",
                width=2
            )
            
            # 添加上下文大小标签
            self._draw_debug_text(
                draw, 
                10, 
                10, 
                f"上下文: {capture_area['width']}x{capture_area['height']}", 
                "blue"
            )
            
            # 保存回文件
            img.save(screenshot_path, "PNG")
            logger.info(f"已添加调试覆盖层到截图: {screenshot_path}")
            
        except Exception as e:
            logger.error(f"添加调试覆盖层时出错: {str(e)}")

    def _draw_debug_text(self, draw, x, y, text, color):
        """在图像上绘制调试文本"""
        try:
            from PIL import ImageFont
            # 尝试加载系统字体
            try:
                font = ImageFont.truetype("arial.ttf", 14)
            except Exception:
                try:
                    font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 14)
                except Exception:
                    font = ImageFont.load_default()
            draw.text((x, y), text, fill=color, font=font)
        except Exception as e:
            logger.warning(f"使用默认字体绘制文本: {str(e)}")
            draw.text((x, y), text, fill=color)