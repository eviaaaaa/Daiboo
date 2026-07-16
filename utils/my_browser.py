from pathlib import Path
import asyncio
import subprocess
import atexit
import json
import os
import sys
import typing
from dotenv import load_dotenv
from loguru import logger

from utils.config import project_env_file, project_root

# 加载项目根目录 .env 依赖
load_dotenv(dotenv_path=project_env_file())

_PORT_ERROR = "DEBUGGING_PORT must be an integer between 1 and 65535"
_HEADLESS_ERROR = "BROWSER_HEADLESS must be one of: auto, true, false"
_PROJECT_ROOT = project_root()


def _validate_port(port: int) -> int:
    if not 1 <= port <= 65535:
        raise ValueError(_PORT_ERROR)
    return port


def _env_text(name: str, default: str) -> str:
    return (os.getenv(name) or "").strip() or default


def _env_path(name: str, default: str) -> Path:
    raw_path = _env_text(name, default)
    if len(raw_path) >= 3 and raw_path[1] == ":" and raw_path[2] in {"\\", "/"}:
        return Path(raw_path)

    path = Path(raw_path).expanduser()
    if path.is_absolute():
        return path
    return _PROJECT_ROOT / path


def _env_port(name: str, default: str) -> int:
    raw_port = _env_text(name, default)
    try:
        port = int(raw_port)
    except (TypeError, ValueError) as exc:
        raise ValueError(_PORT_ERROR) from exc

    return _validate_port(port)


def _env_headless() -> str:
    value = _env_text("BROWSER_HEADLESS", "auto").lower()
    if value not in {"auto", "true", "false"}:
        raise ValueError(_HEADLESS_ERROR)
    return value


# ========================
# 配置区
# ========================
BROWSER_PATH = _env_text("BROWSER_PATH", r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe")
# 或 Chrome: r"C:\Program Files\Google\Chrome\Application\chrome.exe"

# 使用临时目录避免权限问题
USER_DATA_DIR = _env_path("USER_DATA_DIR", r"C:\playwright_edge_refined")
DEBUGGING_PORT = _env_port("DEBUGGING_PORT", "9222")
BROWSER_HEADLESS = _env_headless()

# 用于保存浏览器子进程的全局变量
browser_process: typing.Optional[subprocess.Popen] = None

# ========================
# 辅助函数
# ========================
async def check_port_in_use(port: int) -> bool:
    """异步检查指定端口是否已被占用。"""
    try:
        _, writer = await asyncio.open_connection("127.0.0.1", port)
        writer.close()
        await writer.wait_closed()
        return True
    except (ConnectionRefusedError, OSError):
        return False


async def check_cdp_ready(port: int) -> bool:
    """访问 /json/version，确认监听者确实是 Chrome DevTools endpoint。"""
    writer = None
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection("127.0.0.1", port), timeout=1.0
        )
        writer.write(
            (
                "GET /json/version HTTP/1.1\r\n"
                f"Host: 127.0.0.1:{port}\r\n"
                "Connection: close\r\n\r\n"
            ).encode("ascii")
        )
        await writer.drain()
        response = await asyncio.wait_for(reader.read(65536), timeout=1.0)
        header, separator, body = response.partition(b"\r\n\r\n")
        if not separator or b" 200 " not in header.split(b"\r\n", 1)[0]:
            return False
        payload = json.loads(body.decode("utf-8"))
        return bool(payload.get("Browser") and payload.get("webSocketDebuggerUrl"))
    except (OSError, asyncio.TimeoutError, UnicodeDecodeError, json.JSONDecodeError, ValueError):
        return False
    finally:
        if writer is not None:
            writer.close()
            try:
                await writer.wait_closed()
            except OSError:
                pass


def cleanup_browser():
    """atexit 清理函数：如果是由本脚本启动的浏览器，则关闭它。"""
    global browser_process
    if browser_process:
        logger.info("脚本退出，正在关闭由本脚本启动的浏览器进程...")
        browser_process.terminate()
        try:
            browser_process.wait(timeout=5)
            logger.info("浏览器进程已关闭。")
        except subprocess.TimeoutExpired:
            logger.warning("关闭浏览器超时，强制终止。")
            browser_process.kill()
        browser_process = None


# 注册清理函数，确保脚本退出时执行
atexit.register(cleanup_browser)


def _build_browser_command(port: int, *, headless: bool) -> list[str]:
    command = [
        BROWSER_PATH,
        f"--remote-debugging-port={port}",
        f"--user-data-dir={USER_DATA_DIR}",
        "--no-first-run",
        "--disable-default-apps",
        "--disable-popup-blocking",
        "--disable-gpu",
        "--no-sandbox",
        "--disable-dev-shm-usage",
    ]
    if headless:
        command.extend(["--headless=new", "--window-size=1920,1080"])
    else:
        command.append("--start-maximized")
    return command


async def _wait_for_cdp(port: int) -> bool:
    for _ in range(20):
        if await check_cdp_ready(port):
            return True
        if browser_process is not None:
            poll = getattr(browser_process, "poll", None)
            if callable(poll) and poll() is not None:
                return False
        await asyncio.sleep(0.5)
    return False


async def _launch_browser(port: int, *, headless: bool) -> bool:
    global browser_process
    command = _build_browser_command(port, headless=headless)
    logger.debug(
        "浏览器启动命令: {}",
        " ".join(f'"{part}"' if " " in part else part for part in command),
    )
    browser_process = subprocess.Popen(command)
    logger.info("等待浏览器启动并开启 CDP 调试端点...")
    return await _wait_for_cdp(port)


# ========================
# 核心功能
# ========================
async def ensure_browser_running(port: int | None = None):
    """确保浏览器进程运行在指定 CDP 端口。Linux auto 模式失败后 headless 重试一次。"""
    port = DEBUGGING_PORT if port is None else _validate_port(port)
    if await check_cdp_ready(port):
        logger.info("端口 {} 已有 CDP 浏览器运行，跳过启动。", port)
        return
    if await check_port_in_use(port):
        raise RuntimeError(
            f"Port {port} is occupied but is not a Chrome DevTools endpoint."
        )

    logger.info("端口 {} 空闲，正在启动新的浏览器实例...", port)
    os.makedirs(USER_DATA_DIR, exist_ok=True)

    headless_first = BROWSER_HEADLESS == "true"
    if await _launch_browser(port, headless=headless_first):
        logger.info("浏览器实例已就绪。")
        return

    cleanup_browser()
    should_fallback = (
        BROWSER_HEADLESS == "auto"
        and sys.platform.startswith("linux")
        and not headless_first
    )
    if should_fallback:
        logger.warning("有头浏览器启动失败，自动使用 --headless=new 重试一次。")
        if await _launch_browser(port, headless=True):
            logger.info("Headless 浏览器实例已就绪。")
            return
        cleanup_browser()

    raise RuntimeError("浏览器启动超时或 CDP 调试端点未就绪。")
