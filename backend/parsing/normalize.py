"""坐标归一化（docs M1 §3.1）。

为什么必须做：PDF 里的坐标是"点"（1/72 英寸）或像素，
一旦换缩放、换分辨率、换渲染器，数字全变。
存成 0~1 的比例之后，**任何缩放下都能还原到正确位置**。
"""

from __future__ import annotations


def normalize_bbox(bbox: list[float], page_w: float, page_h: float) -> list[float]:
    """[x0, y0, x1, y1]（像素）→ 0~1 的比例。

    顺带裁剪到 [0, 1]：MinerU 偶尔会给出略微越界的框，
    不裁的话前端会把高亮画到页面外面去。
    """
    if page_w <= 0 or page_h <= 0:
        raise ValueError(f"页面尺寸必须为正数，收到 {page_w} x {page_h}")

    x0, y0, x1, y1 = bbox
    return [
        round(_clamp(x0 / page_w), 4),
        round(_clamp(y0 / page_h), 4),
        round(_clamp(x1 / page_w), 4),
        round(_clamp(y1 / page_h), 4),
    ]


def denormalize_bbox(bbox: list[float], page_w: float, page_h: float) -> list[float]:
    """反方向：0~1 的比例 → 当前渲染尺寸下的像素坐标（前端画高亮时用）。"""
    x0, y0, x1, y1 = bbox
    return [x0 * page_w, y0 * page_h, x1 * page_w, y1 * page_h]


def _clamp(v: float) -> float:
    return max(0.0, min(1.0, v))
