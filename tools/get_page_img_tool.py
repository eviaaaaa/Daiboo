from typing import Optional
import base64

from playwright.async_api import Page
from langchain.messages import ToolMessage
from langchain.tools import ToolRuntime
from langchain_community.tools.playwright import utils
from langchain_community.tools.playwright.base import BaseBrowserTool
from langchain_core.callbacks import (
    AsyncCallbackManagerForToolRun,
    CallbackManagerForToolRun,
)


class GetPageImgTool(BaseBrowserTool):
    name: str = "get_page_img"
    description: str = "Capture a screenshot of the current webpage. "

    def _run(
        self,
        runtime:ToolRuntime,
        run_manager: Optional[CallbackManagerForToolRun] = None,
    ) -> str:
        """Use the tool."""
        if self.async_browser is None:
            raise ValueError(f"Asynchronous browser not provided to {self.name}")
        page:Page = utils.aget_current_page(self.async_browser)
        from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
        try:
            img = page.screenshot(type="png")
            imgbase64 = base64.b64encode(img).decode('utf-8')
            # imgBlock:ImageContentBlock = create_image_block(base64=imgbase64,mime_type="image/png")
            tool_message=ToolMessage(content="当前页面截图",content_blocks=[
                {"type":"image","image":f"data:image/png;base64,{imgbase64}"}],
                tool_call_id=f"{runtime.state['messages'][-1].tool_calls[0]['id']}_get_page_img")
            return tool_message
        except PlaywrightTimeoutError:
            return "Unable to capture screenshot"  

    async def _arun(
        self,
        runtime:ToolRuntime,
        run_manager: Optional[AsyncCallbackManagerForToolRun] = None,
    ) -> ToolMessage | str:
        """Use the tool."""
        if self.async_browser is None:
            raise ValueError(f"Asynchronous browser not provided to {self.name}")
        page:Page = await utils.aget_current_page(self.async_browser)
        from playwright.async_api import TimeoutError as PlaywrightTimeoutError
        try:
            img = await page.screenshot(type="png")
            imgbase64 = base64.b64encode(img).decode('utf-8')
            # imgBlock:ImageContentBlock = create_image_block(base64=imgbase64,mime_type="image/png")
            tool_message=ToolMessage(content="当前页面截图",content_blocks=[
                {"type":"image","image":f"data:image/png;base64,{imgbase64}"}],
                tool_call_id=f"{runtime.state['messages'][-1].tool_calls[0]['id']}_get_page_img")
            return tool_message
        except PlaywrightTimeoutError as err:
            print(f"{err}")
            return "Unable to capture screenshot"