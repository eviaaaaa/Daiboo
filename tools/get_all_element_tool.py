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

    def _clean_content(self, content: str) -> str:
        try:
            from bs4 import BeautifulSoup, Comment
        except ImportError:
            return content
            
        soup = BeautifulSoup(content, "html.parser")
        
        # 移除不想要的标签
        for element in soup(["script", "style", "meta", "link", "noscript", "svg", "iframe", "head"]):
            element.decompose()
            
        # 移除内容
        for comment in soup.find_all(string=lambda text: isinstance(text, Comment)):
            comment.extract()
            
        # 白名单
        for tag in soup.find_all(True):
            new_attrs = {}
            for k, v in tag.attrs.items():
                if k in ['id', 'class', 'name', 'type', 'value', 'placeholder', 'aria-label', 'role', 'title', 'alt', 'href']:
                    new_attrs[k] = v
                elif k == 'src' and not str(v).startswith('data:'):
                    new_attrs[k] = v
            tag.attrs = new_attrs
            
        return str(soup)

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
            content = page.content()
            return self._clean_content(content)
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
            content = await page.content()
            return self._clean_content(content)
        except PlaywrightTimeoutError as err:
            print(f"{err}")
            return "Unable to get page content"