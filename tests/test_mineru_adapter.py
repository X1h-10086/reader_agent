"""F-04 验收：MinerU 适配器（翻译 + 坐标归一化 + char_span）。

对应的能力：CAP-M1-03（解析产出 Block）、CAP-M1-04（坐标归一化）。
判定标准：全 [OK]。

用法：
    python -m tests.test_mineru_adapter
"""

import json
import sys
from pathlib import Path

from backend.parsing.adapters.mineru import MinerUAdapter

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

FIXTURE = (
    Path(__file__).resolve().parents[1]
    / "backend" / "parsing" / "fixtures" / "mineru_raw_sample.json"
)

passed = 0
failed = 0


def check(说明: str, 期望, 实际) -> None:
    global passed, failed
    if 期望 == 实际:
        print(f"  [OK] {说明:<38} -> {实际!r}")
        passed += 1
    else:
        print(f"  [!!] {说明:<38} -> 期望 {期望!r}，实际 {实际!r}")
        failed += 1


def main() -> None:
    raw = json.loads(FIXTURE.read_text(encoding="utf-8"))
    blocks = MinerUAdapter(version_id="ver-001").to_blocks(raw)

    by_type = {b.type.value: b for b in blocks}

    # ---------------- 数量与顺序 ----------------
    print("=" * 70)
    print("翻译结果：MinerU 的 7 个原始块 → 我们的 Block")
    print("=" * 70)
    check("原始 7 个块，空块丢弃后剩 6 个", 6, len(blocks))
    check("阅读顺序 idx 连续", list(range(6)), [b.idx for b in blocks])
    check("没有空文本的块", True, all(b.text.strip() for b in blocks))

    # ---------------- 类型映射 ----------------
    print()
    print("=" * 70)
    print("类型映射（它的方言 → 我们的枚举）")
    print("=" * 70)
    check("header → header", True, "header" in by_type)
    check("title → title", True, "title" in by_type)
    check("text → text", True, "text" in by_type)
    check("table → table", True, "table" in by_type)
    check("footer → footer", True, "footer" in by_type)
    check("interline_equation → formula", True, "formula" in by_type)
    check("标题层级 text_level=1 被带出来", 1, by_type["title"].level)

    # ---------------- 页码 ----------------
    print()
    print("=" * 70)
    print("页码：从 0 起 → 从 1 起")
    print("=" * 70)
    check("第一页 page_idx=0 → page=1", 1, by_type["header"].page)
    check("第二页 page_idx=1 → page=2", 2, by_type["formula"].page)

    # ---------------- 坐标归一化 ----------------
    print()
    print("=" * 70)
    print("坐标归一化（CAP-M1-04）")
    print("=" * 70)
    check("所有 bbox 都是 4 个数字", True, all(len(b.bbox) == 4 for b in blocks))
    check("所有 bbox 都在 0~1 之间", True,
          all(0.0 <= v <= 1.0 for b in blocks for v in b.bbox))
    check("raw_bbox 原样保留", [78.0, 95.0, 520.0, 130.0], by_type["title"].raw_bbox)
    check("78.0 / 595 → 0.1311", 0.1311, by_type["title"].bbox[0])
    check("越界坐标被裁到 1.0",
          [1.0, 1.0],
          [by_type["formula"].bbox[1], by_type["formula"].bbox[3]])

    # ---------------- 文本拼接 ----------------
    print()
    print("=" * 70)
    print("多行文本拼接")
    print("=" * 70)
    check("两行 span 拼成一句完整的话",
          "乙方未按期交付的，应按日千分之三支付违约金。",
          by_type["text"].text)

    # ---------------- char_span ----------------
    print()
    print("=" * 70)
    print("char_span：用全文切片能还原出原文")
    print("=" * 70)
    full_text = "\n".join(b.text for b in blocks)
    check("每个 block 的 char_span 切片 == 它自己",
          True,
          all(full_text[b.char_span[0]:b.char_span[1]] == b.text for b in blocks))
    check("char_span 起点递增", True,
          all(blocks[i].char_span[0] < blocks[i + 1].char_span[0] for i in range(len(blocks) - 1)))

    # ---------------- meta ----------------
    print()
    print("=" * 70)
    print("附件信息（表格 HTML / 公式 LaTeX）")
    print("=" * 70)
    check("表格保留 html", True, "html" in by_type["table"].meta)
    check("公式保留 latex", True, "latex" in by_type["formula"].meta)
    check("样例未给置信度 → 标记为「未提供」",
          False, by_type["title"].meta["_adapter"]["confidence_provided"])

    # ---------------- id ----------------
    print()
    print("=" * 70)
    print("标识")
    print("=" * 70)
    check("id 唯一", True, len({b.id for b in blocks}) == len(blocks))
    check("version_id 全部一致", True, all(b.version_id == "ver-001" for b in blocks))

    print()
    print("=" * 70)
    print(f"通过 {passed} 项 [OK] ｜ 失败 {failed} 项 [!!]")
    print("=" * 70)

    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
