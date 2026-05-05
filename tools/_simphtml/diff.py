"""简化 HTML 之间的 signature diff。

移植自 GenericAgent/simphtml.py 的 `find_changed_elements`，仅做注解化。
被 diff_middleware 用来在 MCP 写动作前后自动给出 DOM 变化摘要。
"""
from __future__ import annotations

from bs4 import BeautifulSoup


def _direct_text(el) -> str:
    return "".join(t.strip() for t in el.find_all(string=True, recursive=False)).strip()


def _get_sig(el) -> str:
    attrs = {k: v for k, v in el.attrs.items() if k != "data-track-id"}
    return f"{el.name}:{attrs}:{_direct_text(el)}"


def _build_sigs(soup: BeautifulSoup) -> dict[str, list]:
    result: dict[str, list] = {}
    for el in soup.find_all(True):
        sig = _get_sig(el)
        result.setdefault(sig, []).append(el)
    return result


def find_changed_elements(before_html: str, after_html: str) -> dict:
    """对比前后两版 simplified HTML，返回 DOM 变化摘要。

    返回 dict 含：
    - changed: 变化元素总数
    - top_change: 变化边界中 outerHTML 最长的元素（截断到 2000 字符）
    """
    if not before_html or not after_html:
        return {"changed": 0}

    before_soup = BeautifulSoup(before_html, "html.parser")
    after_soup = BeautifulSoup(after_html, "html.parser")

    before_sigs = _build_sigs(before_soup)
    after_sigs = _build_sigs(after_soup)

    changed = []
    for sig, els in after_sigs.items():
        if sig not in before_sigs:
            changed.extend(els)
        elif len(els) > len(before_sigs[sig]):
            changed.extend(els[: len(els) - len(before_sigs[sig])])

    if len(changed) == 0 and str(before_soup) != str(after_soup):
        before_els = before_soup.find_all(True)
        after_els = after_soup.find_all(True)
        for i in range(min(len(before_els), len(after_els))):
            if _get_sig(before_els[i]) != _get_sig(after_els[i]):
                changed.append(after_els[i])

    cids = set(id(el) for el in changed)
    boundaries = [el for el in changed if el.parent is None or id(el.parent) not in cids]
    top = max(boundaries, key=lambda el: len(str(el))) if boundaries else None

    result: dict = {"changed": len(changed)}
    if top is not None:
        h = str(top)
        result["top_change"] = h if len(h) <= 2000 else h[:2000] + "...[TRUNCATED]"
    return result
