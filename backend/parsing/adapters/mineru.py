"""MinerU 适配器（docs M1 §3.1）。

**唯一职责**：把 MinerU 的方言翻译成我们自己的 Block[]。

全项目**只有这个文件**允许出现 MinerU 的字段名
（pdf_info / para_blocks / lines / spans ...）。

它哪天升级改了字段？只改这里。下游的切片、检索、规则、前端，一行都不用动。
"""

from __future__ import annotations

from backend.core.enums import BlockType
from backend.core.models import Block
from backend.parsing.normalize import normalize_bbox

# MinerU 的类型名 → 我们 enums.py 里的 BlockType
_TYPE_MAP: dict[str, BlockType] = {
    "title": BlockType.TITLE,
    "text": BlockType.TEXT,
    "table": BlockType.TABLE,
    "image": BlockType.FIGURE,
    "interline_equation": BlockType.FORMULA,
    "header": BlockType.HEADER,
    "footer": BlockType.FOOTER,
    "page_number": BlockType.FOOTER,
}


class MinerUAdapter:
    """把 MinerU 的原始 JSON 变成 list[Block]。

    用法：
        adapter = MinerUAdapter(version_id="ver-001")
        blocks = adapter.to_blocks(raw_json)
    """

    def __init__(self, version_id: str, id_prefix: str = "blk") -> None:
        self.version_id = version_id
        self.id_prefix = id_prefix

    # ------------------------------------------------------------ 主流程

    def to_blocks(self, raw: dict) -> list[Block]:
        blocks: list[Block] = []
        idx = 0

        for page in raw.get("pdf_info", []):
            page_w, page_h = page["page_size"]
            page_no = int(page.get("page_idx", 0)) + 1     # MinerU 从 0 起，人看从 1 起

            for para in page.get("para_blocks", []):
                text = self._join_text(para)

                # 空块直接丢弃：全空白的框 downstream 只会制造噪音
                if not text.strip():
                    continue

                conf, conf_provided = self._confidence(para)

                meta = self._meta(para)
                # 保留键：记录这个置信度是「引擎给的」还是「我们默认填的」
                meta.setdefault("_adapter", {})["confidence_provided"] = conf_provided

                blocks.append(
                    Block(
                        id=f"{self.id_prefix}-{idx:04d}",
                        version_id=self.version_id,
                        idx=idx,
                        type=_TYPE_MAP.get(para.get("type", "text"), BlockType.TEXT),
                        text=text,
                        page=page_no,
                        bbox=normalize_bbox(para["bbox"], page_w, page_h),
                        raw_bbox=para["bbox"],
                        char_span=None,                     # 下面统一回填
                        level=self._level(para),
                        confidence=conf,
                        meta=meta,
                    )
                )
                idx += 1

        self._assign_char_spans(blocks)
        return blocks

    # ------------------------------------------------------------ 字段翻译

    @staticmethod
    def _join_text(para: dict) -> str:
        """把 lines → spans 里的文字拼成一整段。"""
        return "".join(
            span.get("content", "")
            for line in para.get("lines", [])
            for span in line.get("spans", [])
        )

    @staticmethod
    def _level(para: dict) -> int | None:
        """标题层级。MinerU 不同版本把它放在 text_level 或 level。"""
        lv = para.get("text_level") or para.get("level")
        return int(lv) if lv else None

    @staticmethod
    def _confidence(para: dict) -> tuple[float, bool]:
        """返回（数值, 是否真的由引擎提供）。

        为什么还要第二个值：MinerU 有些模式根本不输出 confidence。
        这时字段总得填个数（Block 要求 float），但**必须把它标记成"假的"**，
        否则质量评分会拿一个凭空的 1.0 当成"识别得很准"。
        """
        if para.get("confidence") is None:
            return 1.0, False
        try:
            v = float(para["confidence"])
        except (TypeError, ValueError):
            return 1.0, False
        return max(0.0, min(1.0, v)), True

    @staticmethod
    def _meta(para: dict) -> dict:
        """把下游要用的附件信息带出来：表格 HTML、公式 LaTeX。"""
        meta: dict = {}
        if para.get("html"):
            meta["html"] = para["html"]
        if para.get("latex"):
            meta["latex"] = para["latex"]
        return meta

    # ------------------------------------------------------------ char_span

    @staticmethod
    def _assign_char_spans(blocks: list[Block], sep: str = "\n") -> str:
        """回填每个 block 在全文中的字符区间，并返回拼好的 full_text。

        为什么它是「高分项」（docs M1 §4）：
        M5 要校验"LLM 引用的这句话真的是原文吗"。有了 char_span，
        直接 full_text[start:end] == quote 就能比，不必再依赖坐标 —— 又快又准。
        """
        buf: list[str] = []
        pos = 0
        for b in blocks:
            b.char_span = (pos, pos + len(b.text))
            buf.append(b.text)
            pos += len(b.text) + len(sep)
        return sep.join(buf)
