"""探针台用的章节树与切片能力（CAP-M2-01 / CAP-M2-02）。

为什么要单独一份"多章节合同"样例：
    上一份样例只有 6 个块、1 个标题，看不出层级与切片的差别。
    这一份有 3 级标题、正文、表格、页脚，正好能演示结构优先切片的效果。
"""

from __future__ import annotations

import json
from pathlib import Path

from backend.parsing.adapters.mineru import MinerUAdapter
from backend.representation.chunker import build_chunks
from backend.representation.section_tree import SectionNode, build_section_tree

FIXTURE = (
    Path(__file__).resolve().parents[1]
    / "parsing" / "fixtures" / "mineru_contract_sample.json"
)


def _load():
    raw = json.loads(FIXTURE.read_text(encoding="utf-8"))
    blocks = MinerUAdapter(version_id="ver-demo").to_blocks(raw)
    return blocks, len(raw.get("pdf_info", []))


def _node_to_dict(node: SectionNode) -> dict:
    return {
        "title": node.title,
        "level": node.level,          # null 表示「推不出来，不硬猜」
        "path": node.path,
        "own_blocks": len(node.blocks),
        "children": [_node_to_dict(c) for c in node.children],
    }


def tree_demo() -> dict:
    """CAP-M2-01：把平铺的 Block 组织成章节树。"""
    blocks, pages = _load()
    tree = build_section_tree(blocks)

    标题数 = sum(1 for b in blocks if b.type.value == "title")
    return {
        "来源": "内置样例 mineru_contract_sample.json",
        "页数": pages,
        "块数": len(blocks),
        "标题数": 标题数,
        "说明": "level 为 null 表示编号也推不出层级 —— 不硬猜，交给前端按平级显示",
        "树": _node_to_dict(tree),
    }


def chunk_demo(max_chars: int = 500, overlap: int = 80) -> dict:
    """CAP-M2-02：按章节切片，并注入章节路径前缀。

    把 max_chars 调小（比如 60）再执行一次，能看到切片数量随之变化 ——
    这就是 docs/05 里 CAP-M2-02 的判据。
    """
    max_chars = int(max_chars)
    overlap = int(overlap)

    if max_chars < 50:
        return {"error": f"max_chars 太小（{max_chars}），至少 50"}

    # 调小 max_chars 时 overlap 往往就"超界"了。不报错，自动收敛到合理值，
    # 并把这件事写进结果 —— 参数不合法时给一个能继续跑的默认值，比直接甩错误好。
    调整说明 = None
    if overlap < 0 or overlap >= max_chars:
        原值 = overlap
        overlap = max(10, max_chars // 4)
        调整说明 = f"overlap={原值} 不合法（必须小于 max_chars），已自动调整为 {overlap}"

    blocks, _ = _load()
    chunks = build_chunks(blocks, "ver-demo", max_chars=max_chars, overlap=overlap)

    return {
        "参数": {"max_chars": max_chars, "overlap": overlap},
        "参数调整": 调整说明,
        "chunk 数": len(chunks),
        "提示": "把 max_chars 改小再执行，chunk 数会变多 —— 但每个 chunk 仍然不会跨章节",
        "chunks": [
            {
                "id": c.id,
                "section_path": c.section_path,
                "page": c.page,
                "tokens": c.tokens,
                "block_ids": c.block_ids,
                "text": c.text,
            }
            for c in chunks
        ],
    }
