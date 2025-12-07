from typing import Optional, Type

from pydantic import BaseModel, Field
from playwright.async_api import Page
from langchain_community.tools.playwright import utils
from langchain_community.tools.playwright.base import BaseBrowserTool
from langchain_core.callbacks import (
    AsyncCallbackManagerForToolRun,
    CallbackManagerForToolRun,
)




class FillTextToolInput(BaseModel):
    """Input for ClickTool."""

    selector: str = Field(..., description="CSS selector for the element to fill")
    text: str = Field(..., description="Text to fill into the input field")

class FillTextTool(BaseBrowserTool):
    name: str = "fill_text"
    description: str = "Fill text into an input field identified by the selector"
    args_schema: Type[BaseModel] = FillTextToolInput

    def _run(
        self,
        selector: str,
        text: str,
        run_manager: Optional[CallbackManagerForToolRun] = None,
    ) -> str:
        """Use the tool."""
        if self.async_browser is None:
            raise ValueError(f"Asynchronous browser not provided to {self.name}")
        page:Page = utils.aget_current_page(self.async_browser)
        from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
        try:
            page.fill(
                selector,
                text,
            )
            print("filled")
            page.screenshot(path="fill.png")
        except PlaywrightTimeoutError:
            return f"Unable to fill on element '{selector}'"
        return f"fill element '{selector}' successfully"

    async def _arun(
        self,
        selector: str,
        text: str,
        run_manager: Optional[AsyncCallbackManagerForToolRun] = None,
    ) -> str:
        """Use the tool."""
        if self.async_browser is None:
            raise ValueError(f"Asynchronous browser not provided to {self.name}")
        page:Page = await utils.aget_current_page(self.async_browser)
        from playwright.async_api import TimeoutError as PlaywrightTimeoutError
        try:
            await page.fill(
                selector,
                text,
            )
            print("filled")
            await page.screenshot(path="./screen/fill.png")
        except PlaywrightTimeoutError:
            return f"Unable to fill on element '{selector}'"
        return f"fill element '{selector}' successfully"