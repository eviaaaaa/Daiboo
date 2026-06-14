"""solve_hcaptcha 工具：把 `hcaptcha-challenger` 包装成 langchain 工具。

定位
    现有 MCP 视觉链对真实 hCaptcha（特别是事件可信度检测、跨域 iframe 反指纹）几乎不可用。
    epic-freebies-helper 的解法是直接调用 `hcaptcha-challenger` 提供的 AgentV：它会在
    Playwright Page 上完成"识别挑战类型 → 多模态分类 → 带贝塞尔轨迹的可信点击 → 多轮挑战"。
    本工具把这个能力暴露给我们项目的 agent —— agent 自己只负责"先点 checkbox（或先 navigate）→
    遇到挑战时调用 solve_hcaptcha → 之后照常 snapshot/click 走表单"。

约束
    - 依赖 `hcaptcha-challenger`。
    - LLM provider 走 `extensions/llm_adapter.py`：
        * LLM_PROVIDER=glm + GLM_API_KEY 已配置时，自动 monkey-patch google.genai，
          所有请求改走 GLM_BASE_URL（默认 https://open.bigmodel.cn/api/paas/v4）。
          推荐模型 GLM_MODEL=glm-4.6v。
        * LLM_PROVIDER=gemini 或缺省时，走原生 Gemini，需要真实 GEMINI_API_KEY。
    - hcaptcha-challenger 在 AgentConfig 内强校验 GEMINI_API_KEY 字段非空，
      本工具会在 GLM 模式下自动用 GLM_API_KEY 填充该字段（仅占位，真实流量已被 patch 接管）。
    - 必须有一个 CDP-debug 端口可用的 Chromium 系浏览器；本仓库的 utils.my_browser 已经
      把 Edge 起在 http://127.0.0.1:9222。MCP 与本工具会共享同一个浏览器进程。
    - 在 Chromium 上 hCaptcha 反指纹依然可能拦截；想最大化通过率仍需 Camoufox。本工具
      允许用户感知失败并按 prompt 第 7 节降级声明边界。

参数
    click_checkbox    : 调用前是否先让 robotic_arm 点 "I'm a robot" 复选框。
                        如果 agent 已经通过 MCP `browser_click` 点过，置为 False 避免重复触发。
    target_url_hint   : 用于在多 tab 情况下挑出目标 page。默认 "hcaptcha"。
    timeout_seconds   : wait_for_challenge 的总超时（秒），默认 120。
    ignore_questions  : 跳过指定的挑战提问（例如 hCaptcha 偶尔出现的 "Drag each segment ..."）。

返回
    JSON 字符串，含 status / message / captcha_response（如果库给出最后一次响应）。
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any, List, Optional, Type

from langchain_core.callbacks import AsyncCallbackManagerForToolRun
from langchain_core.tools import BaseTool
from pydantic import BaseModel, ConfigDict, Field

logger = logging.getLogger(__name__)


def default_cdp_endpoint() -> str:
    configured = (os.getenv("BROWSER_CDP_ENDPOINT") or "").strip()
    if configured:
        return configured
    debugging_port = (os.getenv("DEBUGGING_PORT") or "").strip() or "9222"
    return f"http://127.0.0.1:{debugging_port}"


DEFAULT_TARGET_URL_HINT = "hcaptcha"


def _classify_solver_exception(exc: Exception) -> tuple[str, bool]:
    """把 hcaptcha solver 异常归类成更稳定的 code，并标记是否值得重试。"""
    message = str(exc)
    lowered = message.lower()

    if "validationerror" in lowered or "input should be" in lowered:
        return "solver_schema_mismatch", False

    if "cannot find a valid challenge frame" in lowered:
        return "challenge_frame_not_found", False

    if "nonetype" in lowered and "locator" in lowered:
        return "solver_internal_frame_state_error", False

    if "wait for captcha payload to timeout" in lowered:
        return "challenge_payload_timeout", False

    return exc.__class__.__name__, False


class HCaptchaSolverInput(BaseModel):
    """solve_hcaptcha 工具的入参。"""

    model_config = ConfigDict(extra="forbid")

    click_checkbox: bool = Field(
        default=True,
        description=(
            "是否让 hcaptcha-challenger 内部的 robotic_arm 点击 'I'm a robot' 复选框。"
            "若你已经通过 browser_click 点过 checkbox 并看到挑战面板已经弹出，请传 False。"
        ),
    )
    target_url_hint: str = Field(
        default=DEFAULT_TARGET_URL_HINT,
        description=(
            "用于在多个标签页中识别需要解 captcha 的 page；按 URL 子串匹配。"
            "默认 'hcaptcha'，对 demo 和大多数嵌入站点都生效。匹配不到时回退到最后一个 page。"
        ),
    )
    timeout_seconds: float = Field(
        default=120.0,
        ge=10.0,
        le=600.0,
        description="hcaptcha-challenger 等待并解决挑战的总超时（秒）。",
    )
    ignore_questions: Optional[List[str]] = Field(
        default=None,
        description=(
            "需要跳过的挑战提问字符串列表，例如 ['Drag each segment to its position on the line']。"
            "命中后 hcaptcha-challenger 不会处理该题，便于规避当前模型链解不出的题型。"
        ),
    )


def _summarize_captcha_response(cr: Any) -> dict:
    """把 hcaptcha-challenger 的 CaptchaResponse 压成简短 dict，避免把长字段塞回 LLM。"""
    try:
        dump = cr.model_dump(by_alias=True)
    except Exception:
        return {"raw": str(cr)[:300]}

    keep = {}
    for key in ("requesterQuestion", "requestType", "is_pass", "passed", "pass", "answers"):
        if key in dump:
            keep[key] = dump[key]
    if not keep:
        for key in list(dump.keys())[:5]:
            value = dump[key]
            if isinstance(value, (str, int, float, bool)) or value is None:
                keep[key] = value
            else:
                keep[key] = str(value)[:200]
    return keep


async def _pick_target_page(browser: Any, hint: str):
    """在已连接 CDP 的浏览器里挑一个目标 page；优先匹配 URL 子串，否则取 pages[-1]。"""
    contexts = browser.contexts
    if not contexts:
        raise RuntimeError("CDP 浏览器没有任何 BrowserContext，无法解 hCaptcha。")

    candidate = []
    for ctx in contexts:
        for page in ctx.pages:
            candidate.append(page)
    if not candidate:
        raise RuntimeError("CDP 浏览器没有任何打开的 page，无法解 hCaptcha。")

    if hint:
        hint_lower = hint.lower()
        for page in candidate:
            try:
                if hint_lower in (page.url or "").lower():
                    return page
            except Exception:
                continue

    return candidate[-1]


class HCaptchaSolverTool(BaseTool):
    """调 hcaptcha-challenger 在当前浏览器 page 上自动完成 hCaptcha 校验。"""

    name: str = "solve_hcaptcha"
    description: str = (
        "用 hcaptcha-challenger 库在当前浏览器（CDP 端口 9222）的目标 page 上自动通过 hCaptcha。"
        "它内部完成：跨域 iframe 定位、多模态识别、带贝塞尔轨迹的可信点击、多轮挑战。"
        "调用前**不要**自己 browser_click hCaptcha checkbox：solver 必须在 checkbox 被点之前"
        "注册 `/getcaptcha/` 响应监听器，外部预点会让监听器丢失 payload，"
        "落到不可靠的视觉兜底。请直接传 click_checkbox=True 让 solver 内部去点。"
        "需要 LLM_PROVIDER=glm + GLM_API_KEY（推荐）或 GEMINI_API_KEY；都缺失会立即返回错误，不要重试。"
        "运行成功 ≠ hCaptcha 一定通过：要继续 web_observe / browser_snapshot 复核成功信号再决定是否提交表单。"
    )

    args_schema: Type[BaseModel] = HCaptchaSolverInput

    cdp_endpoint: str = Field(default_factory=default_cdp_endpoint, exclude=True)

    def _run(self, **_: Any) -> str:
        raise NotImplementedError("solve_hcaptcha 仅支持异步调用，请用 _arun")

    async def _arun(
        self,
        *,
        click_checkbox: bool = True,
        target_url_hint: str = DEFAULT_TARGET_URL_HINT,
        timeout_seconds: float = 120.0,
        ignore_questions: Optional[List[str]] = None,
        run_manager: Optional[AsyncCallbackManagerForToolRun] = None,
        **_: Any,
    ) -> str:
        provider = (os.getenv("LLM_PROVIDER", "") or "").strip().lower()
        glm_key = os.getenv("GLM_API_KEY", "").strip()
        gemini_key = os.getenv("GEMINI_API_KEY", "").strip()
        glm_model = os.getenv("GLM_MODEL", "glm-4.6v").strip() or "glm-4.6v"

        if provider == "glm":
            if not glm_key:
                return json.dumps(
                    {
                        "status": "error",
                        "code": "missing_glm_api_key",
                        "message": "LLM_PROVIDER=glm 但 GLM_API_KEY 为空，无法走 GLM 路径。",
                    },
                    ensure_ascii=False,
                )
            # AgentConfig 会硬校验 GEMINI_API_KEY；apply_glm_patch 会接管 google.genai 的真实
            # 请求路径，所以这里把 GEMINI_API_KEY 填成 GLM key 仅作占位。
            if not gemini_key:
                os.environ["GEMINI_API_KEY"] = glm_key
        elif not gemini_key:
            return json.dumps(
                {
                    "status": "error",
                    "code": "missing_gemini_api_key",
                    "message": (
                        "未检测到 GEMINI_API_KEY，也未启用 LLM_PROVIDER=glm。"
                        "请在 .env 中配置 GEMINI_API_KEY 或 LLM_PROVIDER=glm + GLM_API_KEY。"
                    ),
                },
                ensure_ascii=False,
            )

        # apply_llm_patch 必须在 import hcaptcha_challenger 前调用，否则 genai.Client 已被绑定。
        try:
            from extensions.llm_adapter import apply_llm_patch
            patched_provider = apply_llm_patch()
        except Exception as exc:
            return json.dumps(
                {
                    "status": "error",
                    "code": "llm_patch_failed",
                    "message": f"apply_llm_patch 失败：{exc}",
                },
                ensure_ascii=False,
            )
        logger.info("hcaptcha-challenger LLM provider patched: %s", patched_provider)

        try:
            from hcaptcha_challenger import AgentConfig, AgentV  # type: ignore
        except ImportError as exc:
            return json.dumps(
                {
                    "status": "error",
                    "code": "missing_dependency",
                    "message": (
                        f"未安装 hcaptcha-challenger（ImportError: {exc}）。"
                        "请在 conda 环境 langchainenv 中执行：pip install hcaptcha-challenger。"
                    ),
                },
                ensure_ascii=False,
            )

        try:
            from playwright.async_api import async_playwright
        except ImportError as exc:
            return json.dumps(
                {
                    "status": "error",
                    "code": "missing_dependency",
                    "message": f"未安装 playwright：{exc}",
                },
                ensure_ascii=False,
            )

        agent_config_kwargs: dict = {
            "DISABLE_BEZIER_TRAJECTORY": False,
            "WAIT_FOR_CHALLENGE_VIEW_TO_RENDER_MS": 3000,
            "EXECUTION_TIMEOUT": float(timeout_seconds),
        }
        if patched_provider == "glm":
            # 让所有 reasoner 都用 GLM 模型；CHALLENGE_CLASSIFIER 默认 fast-shot，
            # 但库里也可以接受同一个 model 名。
            agent_config_kwargs.update(
                {
                    "CHALLENGE_CLASSIFIER_MODEL": glm_model,
                    "IMAGE_CLASSIFIER_MODEL": glm_model,
                    "SPATIAL_POINT_REASONER_MODEL": glm_model,
                    "SPATIAL_PATH_REASONER_MODEL": glm_model,
                }
            )
        if ignore_questions:
            agent_config_kwargs["ignore_request_questions"] = list(ignore_questions)

        try:
            agent_config = AgentConfig(**agent_config_kwargs)
        except Exception as exc:
            return json.dumps(
                {
                    "status": "error",
                    "code": "agent_config_invalid",
                    "message": f"构造 AgentConfig 失败：{exc}",
                },
                ensure_ascii=False,
            )

        async with async_playwright() as p:
            try:
                browser = await p.chromium.connect_over_cdp(self.cdp_endpoint)
            except Exception as exc:
                return json.dumps(
                    {
                        "status": "error",
                        "code": "cdp_connect_failed",
                        "message": (
                            f"无法通过 CDP 连接 {self.cdp_endpoint}（{exc}）。"
                            "请确认 utils.my_browser.ensure_browser_running() 已经启动调试端口。"
                        ),
                    },
                    ensure_ascii=False,
                )

            try:
                page = await _pick_target_page(browser, target_url_hint)
            except Exception as exc:
                await browser.close()
                return json.dumps(
                    {"status": "error", "code": "no_target_page", "message": str(exc)},
                    ensure_ascii=False,
                )

            # 关键时序：AgentV.__init__ 才注册 page.on("response", _task_handler)。
            # 如果 challenge iframe 已经存在，说明 hCaptcha 早就发过 /getcaptcha/，
            # 那次响应永远不会被监听器看到，wait_for_challenge 必然 payload-timeout。
            # 解决：在构造 AgentV 之前 reload 页面，把 hCaptcha 状态完全归零。
            challenge_already_open = False
            try:
                for f in page.frames:
                    url = f.url or ""
                    if url.startswith("https://newassets.hcaptcha.com/captcha/v1/") and "frame=challenge" in url:
                        challenge_already_open = True
                        break
            except Exception:
                pass

            if challenge_already_open:
                logger.info(
                    "检测到 challenge iframe 已存在（外部预点过 checkbox），"
                    "执行 page.reload 重置 hCaptcha 状态以便监听器能捕获 /getcaptcha/。"
                )
                try:
                    await page.reload(wait_until="domcontentloaded")
                    await page.wait_for_timeout(1500)
                except Exception as exc:
                    logger.warning("page.reload 失败，继续走流程：%s", exc)
                # reload 之后 checkbox 必然回到未点状态，强制内部点击。
                click_checkbox = True

            agent = AgentV(page=page, agent_config=agent_config)

            try:
                if click_checkbox:
                    try:
                        await agent.robotic_arm.click_checkbox()
                    except Exception as exc:
                        logger.warning("robotic_arm.click_checkbox 失败，继续走 wait_for_challenge：%s", exc)

                await agent.wait_for_challenge()
            except Exception as exc:
                code, retryable = _classify_solver_exception(exc)
                summary = {
                    "status": "fail",
                    "code": code,
                    "retryable": retryable,
                    "message": f"hcaptcha-challenger 解题阶段抛出异常：{exc}",
                }
                cr_list = getattr(agent, "cr_list", None) or []
                if cr_list:
                    summary["last_captcha_response"] = _summarize_captcha_response(cr_list[-1])
                return json.dumps(summary, ensure_ascii=False)
            finally:
                # CDP 连接的 browser.close() 只断开本次连接，不会真把 Edge 主进程关掉
                try:
                    await browser.close()
                except Exception:
                    pass

        cr_list = getattr(agent, "cr_list", None) or []
        if cr_list:
            return json.dumps(
                {
                    "status": "ok",
                    "message": (
                        "hcaptcha-challenger 已结束 wait_for_challenge。"
                        "请用 web_observe / browser_snapshot 复核外层成功信号后再决定提交表单。"
                    ),
                    "last_captcha_response": _summarize_captcha_response(cr_list[-1]),
                    "rounds": len(cr_list),
                },
                ensure_ascii=False,
            )

        return json.dumps(
            {
                "status": "ok",
                "message": (
                    "hcaptcha-challenger 已结束，但未产生 captcha_response。"
                    "可能挑战已在弹出前自动通过、或外层 checkbox 未实际触发。"
                    "请用 web_observe 复核当前页面状态。"
                ),
                "rounds": 0,
            },
            ensure_ascii=False,
        )
