"""章节树 SectionTree（M2 §3.1）。

三条规则照抄文档：

1. 优先用解析器给的层级（`Block.level`，来自 PDF 书签或 MinerU 的标题识别）；
2. 没有层级时，用编号正则兜底（"3.2.1 xxx"、"第三章 xxx"、"一、"）；
3. **兜底也判断不出来时，level 记 None，不硬猜。**

第 3 条最难做到但最重要：硬猜出来的章节树看起来完整，其实层级是错的，
"章节完整性"这类规则会全部失效 —— 而且没人看得出来是错的。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from backend.core.models import Block

# "3.1" / "3.1.2" / "第三章" / "一、" 这类编号
_NUMBERED = re.compile(
    r"^\s*(第[一二三四五六七八九十百]+[章节条]|\d+(?:\.\d+)*[\.、\s]|[一二三四五六七八九十]+、)"
)


@dataclass
class SectionNode:
    title: str
    level: int | None            # None = 没把握（不硬猜）
    path: str                    # "3 责任 > 3.2 验收"
    stack_level: int             # 内部用：决定挂在树的哪一层
    block_id: str | None = None  # 标题块自己的 id（虚拟根节点为 None）
    children: list["SectionNode"] = field(default_factory=list)
    blocks: list[Block] = field(default_factory=list)   # 直属本节的正文块


def guess_level(text: str) -> int | None:
    """从标题文字里的编号推断层级；推不出来就返回 None。"""
    m = _NUMBERED.match(text)
    if not m:
        return None

    token = m.group(1)
    if token.startswith("第"):
        return 1                                  # 第三章 → 一级

    digits = re.match(r"(\d+(?:\.\d+)*)", token)
    if digits:
        return digits.group(1).count(".") + 1     # 3.1 → 二级，3.1.2 → 三级

    return 1                                      # 一、


def build_section_tree(blocks: list[Block]) -> SectionNode:
    """把平铺的 Block[] 组织成章节树。"""
    root = SectionNode(title="（全文）", level=0, path="", stack_level=0)
    stack: list[SectionNode] = [root]

    for b in sorted(blocks, key=lambda x: x.idx):
        # 正文块挂到当前最深的那一节
        if b.type.value != "title":
            stack[-1].blocks.append(b)
            continue

        level = b.level if b.level is not None else guess_level(b.text)
        # mount 只决定"挂在哪一层"，与 level 是否可信无关
        mount = level if level is not None else (stack[-1].stack_level + 1)

        while len(stack) > 1 and stack[-1].stack_level >= mount:
            stack.pop()

        parent = stack[-1]
        path = f"{parent.path} > {b.text}" if parent.path else b.text
        node = SectionNode(
            title=b.text, level=level, path=path, stack_level=mount, block_id=b.id
        )
        parent.children.append(node)
        stack.append(node)

    return root


def iter_sections(root: SectionNode):
    """先序遍历：父节点在前，子节点在后 —— 正好是文档的阅读顺序。"""
    yield root
    for child in root.children:
        yield from iter_sections(child)


def iter_sections_with_blocks(root: SectionNode):
    """只产出「自己有正文块」的节点，顺序仍然是阅读顺序。"""
    for node in iter_sections(root):
        if node.blocks:
            yield node
