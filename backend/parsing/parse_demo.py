"""基于内置样例的解析能力（探针台 CAP-M1-03/04/05 用）。

为什么用内置样例而不是真 MinerU：
    探针台要验证的是「翻译与定位逻辑对不对」，不是「MinerU 能不能跑」。
    样例在手，任何时候点一下都能复现，不受网络和额度影响。

    真接上 MinerU 之后，这里只需要把 `_load()` 换成调接口 —— 下游一行不改。
"""

from __future__ import annotations

import json
from pathlib import Path

from backend.parsing.adapters.mineru import MinerUAdapter
from backend.parsing.normalize import denormalize_bbox
from backend.parsing.quality import score_blocks

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "mineru_raw_sample.json"


def _load() -> tuple[list, int]:
    """读样例 → 翻译成 Block[]，同时返回页数。"""
    raw = json.loads(FIXTURE.read_text(encoding="utf-8"))
    blocks = MinerUAdapter(version_id="ver-demo").to_blocks(raw)
    return blocks, len(raw.get("pdf_info", []))


def parse_sample() -> dict:
    """CAP-M1-03：跑一遍 Adapter，看带类型的 Block 列表。"""
    blocks, pages = _load()

    统计: dict[str, int] = {}
    for b in blocks:
        统计[b.type.value] = 统计.get(b.type.value, 0) + 1

    return {
        "来源": "内置样例（仿 MinerU 输出，非真实调用）",
        "页数": pages,
        "块数": len(blocks),
        "按类型统计": 统计,
        "blocks": [
            {
                "idx": b.idx,
                "id": b.id,
                "type": b.type.value,
                "page": b.page,
                "level": b.level,
                "text": b.text,
                "bbox": b.bbox,
                "raw_bbox": b.raw_bbox,
                "char_span": list(b.char_span or ()),
            }
            for b in blocks
        ],
    }


def locator_demo(idx: int = 1) -> dict:
    """CAP-M1-04：同一块的原始像素坐标 vs 归一化坐标。"""
    blocks, _ = _load()
    idx = int(idx)

    if not (0 <= idx < len(blocks)):
        return {"error": f"idx 必须在 0~{len(blocks) - 1} 之间，收到 {idx}"}

    b = blocks[idx]
    return {
        "block_id": b.id,
        "type": b.type.value,
        "page": b.page,
        "原文": b.text,
        "原始像素坐标": b.raw_bbox,
        "归一化坐标(0~1)": b.bbox,
        "按 595x842 还原回像素": denormalize_bbox(b.bbox, 595.0, 842.0),
        "为什么这样存": "缩放到 150% 时像素坐标全部放大，归一化坐标不变 —— 所以高亮在任何缩放下都对准",
    }


def quality_demo() -> dict:
    """CAP-M1-05：质量评分 + 分项明细（能说出哪一项拖低了分数）。"""
    blocks, pages = _load()
    return score_blocks(blocks, page_count=pages)
