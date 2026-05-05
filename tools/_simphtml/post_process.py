"""BeautifulSoup 二次清洗 + 预算式递归裁切。

移植自 GenericAgent/simphtml.py 的 `optimize_html_for_tokens` 与 `smart_truncate`，
仅修改：日志改为 logging，函数签名加类型注解。逻辑保持不变。
"""
from __future__ import annotations

import logging
from bs4 import BeautifulSoup, NavigableString, Tag

logger = logging.getLogger(__name__)


# 必须保留的 attribute 白名单。
# 来自 simphtml.py 的原版列表，用于 LLM 阅读 HTML 时仍能保留语义。
_KEEP_ATTRS = {
    "id", "class", "name", "src", "href", "alt", "value", "type", "placeholder",
    "disabled", "checked", "selected", "readonly", "required", "multiple",
    "role", "aria-label", "aria-expanded", "aria-hidden", "contenteditable",
    "title", "for", "action", "method", "target", "colspan", "rowspan",
}


def optimize_html_for_tokens(html_or_soup) -> BeautifulSoup:
    """对 simplified HTML 做二次清洗，进一步压缩 token。

    - SVG 全部 clear 内容并清空属性
    - 删除所有 style 属性
    - 长 src/href/action 替换为 __img__/__url__/__link__
    - 长 value/title/alt 截到 50 字符 + " ..."
    - 非白名单 attribute 删除（保留 short data-* 短值）
    - data-v* (Vue artifact) 整批删除

    返回值是 BeautifulSoup 对象，调用方可继续 `str(soup)` 或 `smart_truncate`。
    """
    if isinstance(html_or_soup, str):
        soup = BeautifulSoup(html_or_soup, "html.parser")
    else:
        soup = html_or_soup

    for svg in soup.find_all("svg"):
        svg.clear()
        svg.attrs = {}

    # style 一律删
    for tag in soup.find_all(True):
        tag.attrs.pop("style", None)

    for tag in soup.find_all(True):
        if tag.has_attr("src"):
            if tag["src"].startswith("data:"):
                tag["src"] = "__img__"
            elif len(tag["src"]) > 30:
                tag["src"] = "__url__"
        if tag.has_attr("href") and len(tag["href"]) > 30:
            tag["href"] = "__link__"
        if tag.has_attr("action") and len(tag["action"]) > 30:
            tag["action"] = "__url__"
        for a in ("value", "title", "alt"):
            if tag.has_attr(a) and isinstance(tag[a], str) and len(tag[a]) > 100:
                tag[a] = tag[a][:50] + " ..."

        for attr in list(tag.attrs.keys()):
            if attr in _KEEP_ATTRS:
                continue
            if attr.startswith("data-v"):
                tag.attrs.pop(attr, None)
            elif attr.startswith("data-") and isinstance(tag[attr], str) and len(tag[attr]) > 20:
                tag[attr] = "__data__"
            elif not attr.startswith("data-"):
                tag.attrs.pop(attr, None)
    return soup


def smart_truncate(soup: BeautifulSoup, budget: int, _depth: int = 0) -> BeautifulSoup:
    """原地递归裁切 soup 使其接近 `budget` 字符。

    策略：
    1. 单子元素 → 穿透 recurse
    2. 多子元素：
       - top 3 子元素总长扛得住 over → 按比例分摊
       - 否则 → 从尾部 decompose 子元素直到回到预算
    3. 始终保护带有 `[FAKE ELEMENT]` 文本的标签（cutlist 留下的提示）
    """
    CUT_THRESHOLD = 8000

    def cut(ele: Tag, keep: int) -> None:
        s = str(ele)
        over = len(s) - keep
        if over <= 0:
            return
        # 保护 FAKE ELEMENT 标签
        protected = [
            c.extract()
            for c in ele.find_all(lambda tag: tag.string and "[FAKE ELEMENT]" in tag.string)
        ]
        s = str(ele)
        over = len(s) - keep
        if over <= 0:
            for p in protected:
                ele.append(p)
            return
        marker = f" [TRUNCATED {over // 1000}k chars]"
        inner = ele.decode_contents()
        tag_overhead = len(s) - len(inner)
        inner_keep = max(keep - tag_overhead - len(marker), 0)
        ele.clear()
        if inner_keep > 0:
            ele.append(BeautifulSoup(inner[:inner_keep], "html.parser"))
        ele.append(NavigableString(marker))
        for p in protected:
            ele.append(p)

    total = len(str(soup))
    if total <= budget:
        return soup
    kids = [
        (c, len(str(c)))
        for c in soup.children
        if c.name and not (c.string and "[FAKE ELEMENT]" in c.string)
    ]
    if not kids:
        return soup
    selflen = total - sum(l for _, l in kids)
    remaining_budget = max(budget - selflen, 0)
    indent = "  " * _depth
    tag_name = getattr(soup, "name", "?")
    logger.debug(
        "%s[smart_truncate] <%s> total=%d budget=%d selflen=%d kids=%d",
        indent, tag_name, total, budget, selflen, len(kids),
    )

    if len(kids) == 1:
        logger.debug("%s  -> single child, recurse into <%s>", indent, kids[0][0].name)
        smart_truncate(kids[0][0], remaining_budget, _depth)
        return soup

    over = sum(l for _, l in kids) - remaining_budget
    if over <= 0:
        return soup

    ranked = sorted(range(len(kids)), key=lambda i: kids[i][1], reverse=True)
    tops = list(ranked[: min(3, len(ranked))])
    top_total = sum(kids[i][1] for i in tops)

    if top_total < over:
        # top 3 扛不住 → 从尾部 decompose
        removed = 0
        removed_count = 0
        while kids and removed < over:
            c, length = kids.pop()
            c.decompose()
            removed += length
            removed_count += 1
        logger.debug(
            "%s  -> tail-cut: removed %d children (%dk chars)",
            indent, removed_count, removed // 1000,
        )
        return soup

    # 按比例分摊（过滤太小的）
    max_size = kids[ranked[0]][1]
    filtered = [i for i in tops if kids[i][1] >= max_size * 0.1]
    filtered_total = sum(kids[i][1] for i in filtered)
    if filtered_total >= over:
        tops, top_total = filtered, filtered_total

    actions = []
    for i in tops:
        c, length = kids[i]
        share = int(over * length / top_total)
        new_keep = length - share
        logger.debug("%s  -> <%s> %d -> %d", indent, c.name, length, new_keep)
        actions.append((c, length, new_keep))
    for c, length, new_keep in actions:
        if new_keep <= 0:
            c.decompose()
        elif new_keep > CUT_THRESHOLD:
            smart_truncate(c, new_keep, _depth + 1)
        else:
            cut(c, new_keep)
    return soup
