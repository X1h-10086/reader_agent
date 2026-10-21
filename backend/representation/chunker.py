"""结构优先切片（M2 §3.2 / §3.3）。

四条硬规则：

1. **禁止跨章节合并** —— 一个 chunk 只能来自同一个 section。
2. 章节太长就滚动窗口二次切，相邻片段保留 overlap，别把上下文切丢。
3. **表格 / 公式整块保留**，单独成 chunk，绝不与正文混切（数值规则依赖它）。
4. 每个 chunk 的正文前缀注入章节路径：`[3 责任 > 3.2 验收] 甲方应在...`
   —— 这样即使只拿出这一块，它自己也说得清出自哪里。
"""

from __future__ import annotations

from backend.core.models import Block, Chunk
from backend.representation.section_tree import (
    build_section_tree,
    iter_sections_with_blocks,
)

MAX_CHARS = 500        # 约 500 token（中文 1 字符 ≈ 1 token 量级）
OVERLAP_CHARS = 80     # 相邻切片重叠的字符数
_KEEP_WHOLE = {"table", "formula"}   # 这几类块整块保留，不切


def build_chunks(
    blocks: list[Block],
    version_id: str,
    max_chars: int = MAX_CHARS,
    overlap: int = OVERLAP_CHARS,
    id_prefix: str = "ck",
) -> list[Chunk]:
    """Block[] → Chunk[]。"""
    tree = build_section_tree(blocks)
    chunks: list[Chunk] = []

    for node in iter_sections_with_blocks(tree):
        for group in _split(node.blocks, max_chars, overlap):
            chunks.append(
                _make_chunk(group, node, version_id, index=len(chunks), id_prefix=id_prefix)
            )

    return chunks


# ------------------------------------------------------------------ 切分

def _split(blocks: list[Block], max_chars: int, overlap: int) -> list[list[Block]]:
    """把同一节内的块分组成若干片，每片不超过 max_chars。"""
    groups: list[list[Block]] = []
    current: list[Block] = []
    size = 0

    def flush() -> None:
        nonlocal current, size
        if current:
            groups.append(current)
        current, size = [], 0

    for b in blocks:
        # 表格 / 公式：整块独占，前后都断开
        if b.type.value in _KEEP_WHOLE:
            flush()
            groups.append([b])
            continue

        b_len = len(b.text)

        if current and size + b_len > max_chars:
            previous = current
            flush()
            # 保留重叠：把上一片尾巴上的整块接到新片开头（仍在本节内）
            for tail in _tail(previous, overlap):
                current.append(tail)
                size += len(tail.text)

        current.append(b)
        size += b_len

    flush()
    return groups


def _tail(blocks: list[Block], budget: int) -> list[Block]:
    """从尾部往前取整块，累计字符数不超过 budget（不切断句子）。"""
    picked: list[Block] = []
    total = 0
    for b in reversed(blocks):
        if picked and total + len(b.text) > budget:
            break
        picked.append(b)
        total += len(b.text)
    return list(reversed(picked))


# ------------------------------------------------------------------ 组装

def _make_chunk(
    blocks: list[Block], node, version_id: str, index: int, id_prefix: str
) -> Chunk:
    text = "".join(b.text for b in blocks)
    section_path = node.path or "（未分章）"
    body = f"[{section_path}] {text}"

    # bbox：同一页内取最小包围盒；跨页时只算首页那些块（跨页框没有意义）
    first_page = blocks[0].page
    same_page = [b for b in blocks if b.page == first_page]
    bbox = [
        min(b.bbox[0] for b in same_page),
        min(b.bbox[1] for b in same_page),
        max(b.bbox[2] for b in same_page),
        max(b.bbox[3] for b in same_page),
    ]

    spans = [b.char_span for b in blocks if b.char_span]
    if spans:
        char_span = (min(s[0] for s in spans), max(s[1] for s in spans))
    else:
        char_span = (0, len(text))

    return Chunk(
        id=f"{id_prefix}-{index:04d}",
        version_id=version_id,
        block_ids=[b.id for b in blocks],
        text=body,
        section_path=section_path,
        page=first_page,
        bbox=bbox,
        char_span=char_span,
        tokens=len(body),        # 粗估：中文里 1 字符 ≈ 1 token
        index_in_doc=index,
    )
