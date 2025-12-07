from typing import Optional

from playwright.async_api import Page
from langchain.messages import ToolMessage
from langchain.tools import ToolRuntime
from langchain_community.tools.playwright import utils
from langchain_community.tools.playwright.base import BaseBrowserTool
from langchain_core.callbacks import (
    AsyncCallbackManagerForToolRun,
    CallbackManagerForToolRun,
)


class GetAllElementTool(BaseBrowserTool):
    name: str = "get_all_element_tool"
    description: str = "Get all elements' content from the current webpage"

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
            return page.content()
        except PlaywrightTimeoutError:
            return "Unable to get page content"
        
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
            return await page.content()
        except PlaywrightTimeoutError as err:
            print(f"{err}")
            return "Unable to get page content"