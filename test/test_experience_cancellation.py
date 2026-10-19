import asyncio
import importlib
from langchain_core.messages import HumanMessage
import pytest


@pytest.mark.asyncio
async def test_cancelling_background_summary_does_not_raise_callback_error(monkeypatch):
    module = importlib.import_module("loggers.experience_middleware")
    started = asyncio.Event()
    release = asyncio.Event()

    async def summarizer(state):
        started.set()
        await release.wait()

    monkeypatch.setattr(module, "_run_experience_summarizer", summarizer)
    loop = asyncio.get_running_loop()
    previous = loop.get_exception_handler()
    errors = []
    before = set(asyncio.all_tasks())
    loop.set_exception_handler(lambda _loop, context: errors.append(context))
    try:
        await module.log_experience.aafter_agent({"messages": [HumanMessage(content="fixture", id="summary-fixture")]}, None)
        await asyncio.wait_for(started.wait(), timeout=2)
        tasks = [task for task in asyncio.all_tasks() - before if task is not asyncio.current_task()]
        assert tasks
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await asyncio.sleep(0)
        assert errors == []
    finally:
        loop.set_exception_handler(previous)
