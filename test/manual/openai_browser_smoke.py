"""Opt-in real OpenAI Responses + isolated Chromium acceptance.

Requires OPENAI_API_KEY/BASE_URL/MODEL. Makes real, potentially billable calls;
never switches providers. No credentials are discovered or written by this file.
Run: uv run python test/manual/openai_browser_smoke.py [--graph] [--report PATH]
The graph option exercises the product factory/middleware, not a mock agent.
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import io
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from langchain_core.messages import HumanMessage, ToolMessage
from langchain_core.tools import StructuredTool
from PIL import Image, ImageDraw, ImageFont
from playwright.async_api import async_playwright
from utils.qwen_model import create_openai_compatible_model, normalize_content
from utils.mcp_client import create_persistent_mcp_session
from tools.browser_runtime import make_browser_runtime_tools
from tools.web_observe_tool import WebObserveTool
import browser_runtime_smoke as fixture


def vision_fixture() -> str:
    image = Image.new("RGB", (700, 180), "white")
    draw = ImageDraw.Draw(image)
    draw.text((35, 45), "ORBIT-314", fill="black", font=ImageFont.load_default(size=70))
    data = io.BytesIO()
    image.save(data, format="PNG")
    return "data:image/png;base64," + base64.b64encode(data.getvalue()).decode()


def message_metrics(message) -> dict:
    return {"model": message.response_metadata.get("model_name"),
            "usage": message.usage_metadata,
            "block_types": [x.get("type") for x in message.content if isinstance(x, dict)]
            if isinstance(message.content, list) else []}


async def protocol_acceptance(model) -> dict:
    calls = []

    async def fixture_probe(marker: str) -> dict:
        """Return the marker through the real local tool result path."""
        calls.append(marker)
        return {"marker": marker, "executed": True}

    tool = StructuredTool.from_function(coroutine=fixture_probe)
    human = HumanMessage(content=[
        {"type": "text", "text": "Read the large code in the image. First call fixture_probe with marker LOCAL_PROBE_OK. After its result, answer with the image code and the returned marker. Do not guess the image code."},
        {"type": "image_url", "image_url": {"url": vision_fixture()}},
    ])
    first = await model.bind_tools([tool], tool_choice="fixture_probe").ainvoke([human])
    assert len(first.tool_calls) == 1 and first.tool_calls[0]["name"] == tool.name
    call = first.tool_calls[0]
    result = await tool.ainvoke(call["args"])
    tool_message = ToolMessage(content=json.dumps(result), tool_call_id=call["id"], name=tool.name)
    final = await model.ainvoke([human, first, tool_message])
    text = normalize_content(final.content)
    assert calls == ["LOCAL_PROBE_OK"], calls
    assert "ORBIT-314" in text and "LOCAL_PROBE_OK" in text, text
    return {"ok": True, "checks": ["native image input", "forced function call", "local tool execution", "call_id replay", "SSE final text"],
            "first": message_metrics(first), "final": message_metrics(final)}


async def browser_acceptance(model, endpoint: str, base: str, saved: list, graph: bool) -> dict:
    async with create_persistent_mcp_session(endpoint) as mcp_tools:
        tools = {t.name: t for t in mcp_tools}
        await tools["browser_navigate"].ainvoke({"url": base})
        helpers = make_browser_runtime_tools(mcp_tools)
        selected = [tools["browser_snapshot"], tools["browser_tabs"], *helpers, WebObserveTool(mcp_tools=mcp_tools)]
        prompt = ("这是隔离的本机测试页，所有数据只保存到本机 fixture；你已获准填写并保存测试数据。"
                  "先观察当前页 #profile 表单，然后将 Name 填为 Model Alice，将 Plan 选为 Pro，点击 Save locally。"
                  "优先使用 browser_batch 把已确认的连续步骤合并，最后断言并读取 #status 的 Saved Model Alice pro。"
                  "不要操作其他站点、终端、验证码或登录。最终简短说明实际读取的保存结果。")
        started = time.perf_counter()
        if graph:
            from utils.agent_factory import create_browser_agent
            agent = await create_browser_agent(mcp_tools)
            state = await agent.ainvoke({"messages": [HumanMessage(content=prompt)]},
                {"configurable": {"thread_id": "openai-browser-smoke-" + uuid.uuid4().hex}, "recursion_limit": 30})
            messages = state["messages"]
            # Let the product's real background summarizer finish on the same
            # authorized provider instead of cancelling it at asyncio.run exit.
            summaries = [task for task in asyncio.all_tasks()
                         if getattr(task.get_coro(), "__name__", "") == "_run_experience_summarizer"]
            if summaries:
                done, pending = await asyncio.wait(summaries, timeout=150)
                if pending:
                    raise RuntimeError("Background experience summary did not finish within the acceptance deadline")
                for task in done:
                    task.result()
        else:
            bound = model.bind_tools(selected, parallel_tool_calls=False)
            messages = [HumanMessage(content=prompt)]
            available = {t.name: t for t in selected}
            for _ in range(12):
                answer = await bound.ainvoke(messages)
                messages.append(answer)
                if not answer.tool_calls:
                    break
                for call in answer.tool_calls:
                    assert call["name"] in available, call["name"]
                    result = await available[call["name"]].ainvoke(call["args"])
                    messages.append(ToolMessage(content=json.dumps(result, ensure_ascii=False, default=str),
                                                tool_call_id=call["id"], name=call["name"]))
            else:
                raise AssertionError("Model exceeded the bounded browser loop")
        elapsed = time.perf_counter() - started
        assert saved and saved[-1] == {"name": "Model Alice", "plan": "pro"}, saved
        # Independent oracle: a fresh direct Playwright CDP read, not model prose.
        async with async_playwright() as pw:
            browser = await pw.chromium.connect_over_cdp(endpoint)
            try:
                page = next(p for c in browser.contexts for p in c.pages if p.url.startswith(base))
                status = await page.locator("#status").inner_text()
                assert "Saved Model Alice pro" in status, status
            finally:
                await browser.close()
        ai = [m for m in messages if m.type == "ai"]
        tool_calls = [c for m in ai for c in m.tool_calls]
        assert any(c["name"] == "browser_batch" for c in tool_calls), "Model did not exercise the batch tool"
        return {"ok": True, "factory_graph": graph, "model_turns": len(ai),
                "tool_calls": [c["name"] for c in tool_calls], "seconds": round(elapsed, 3),
                "saved_record": saved[-1], "independent_status": status,
                "model_usage": [message_metrics(m) for m in ai]}


async def main(args):
    for name in ("OPENAI_API_KEY", "OPENAI_BASE_URL", "OPENAI_MODEL"):
        if not os.getenv(name):
            raise RuntimeError(f"{name} is required for opt-in real acceptance")
    os.environ["DAIBOO_BROWSER_ALLOW_UNSAFE_CODE"] = "false"
    os.environ["DAIBOO_BROWSER_SNAPSHOT_MODE"] = "none"
    model = create_openai_compatible_model(api_mode="responses", streaming=True,
        request_timeout=150, max_output_tokens=2500, max_retries=0, store=False)
    report = {"base_url": os.environ["OPENAI_BASE_URL"], "model": os.environ["OPENAI_MODEL"],
              "protocol": "responses", "streaming": True}
    if not args.browser_only:
        report["protocol_acceptance"] = await protocol_acceptance(model)
    async with async_playwright() as pw:
        executable = os.getenv("CHROMIUM_EXECUTABLE") or pw.chromium.executable_path
        if not Path(executable).is_file():
            candidates = sorted(Path.home().glob(".cache/ms-playwright/chromium-*/chrome-linux64/chrome"))
            executable = str(candidates[-1]) if candidates else shutil.which("chromium")
        if not executable:
            raise RuntimeError("Install Chromium or set CHROMIUM_EXECUTABLE")
    with tempfile.TemporaryDirectory(prefix="daiboo-openai-browser-") as profile, fixture.fixture_server() as (base, saved):
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        process = subprocess.Popen([executable, "--headless=new", "--no-sandbox", "--no-proxy-server",
            "--remote-debugging-address=127.0.0.1", f"--remote-debugging-port={port}",
            f"--user-data-dir={profile}", "--disable-dev-shm-usage", "about:blank"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            await fixture.wait_cdp(port, process)
            report["browser_acceptance"] = await browser_acceptance(model, f"http://127.0.0.1:{port}", base, saved, args.graph)
        finally:
            process.terminate()
            try:
                process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
    report["ok"] = True
    encoded = json.dumps(report, ensure_ascii=False, indent=2)
    if args.report:
        Path(args.report).write_text(encoded, encoding="utf-8")
    print(encoded)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--graph", action="store_true", help="Use the real product factory and middleware")
    parser.add_argument("--browser-only", action="store_true", help="Do not repeat protocol/image acceptance")
    parser.add_argument("--report", help="Optional JSON report (no credentials or reasoning text)")
    asyncio.run(main(parser.parse_args()))
