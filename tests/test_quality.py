"""F-04 验收：质量评分（CAP-M1-05）。

重点是两条「诚实性」：
    ① 引擎没给置信度时，ocr 必须标成 unavailable，而不是假装满分；
    ② 缺失项的权重从分母中剔除，而不是当 0 分算。

用法：
    python -m tests.test_quality
"""

import json
import sys
from pathlib import Path

from backend.parsing.adapters.mineru import MinerUAdapter
from backend.parsing.parse_demo import FIXTURE
from backend.parsing.quality import MEASURED, UNAVAILABLE, score_blocks

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

passed = 0
failed = 0


def check(说明: str, 期望, 实际) -> None:
    global passed, failed
    if 期望 == 实际:
        print(f"  [OK] {说明:<40} -> {实际!r}")
        passed += 1
    else:
        print(f"  [!!] {说明:<40} -> 期望 {期望!r}，实际 {实际!r}")
        failed += 1


def load_raw() -> dict:
    return json.loads(Path(FIXTURE).read_text(encoding="utf-8"))


def add_confidence(raw: dict, value: float) -> dict:
    for page in raw["pdf_info"]:
        for para in page["para_blocks"]:
            para["confidence"] = value
    return raw


def main() -> None:
    # ---------------- 场景 A：引擎没给置信度 ----------------
    raw = load_raw()
    blocks = MinerUAdapter(version_id="ver-a").to_blocks(raw)
    r = score_blocks(blocks, page_count=2)

    print("=" * 72)
    print("场景 A：引擎没给 confidence（当前样例就是这样）")
    print("=" * 72)
    check("ocr 标为 unavailable（不假装满分）", UNAVAILABLE, r["components"]["ocr"]["status"])
    check("ocr 的 value 是 None 而不是数字", None, r["components"]["ocr"]["value"])
    check("权重覆盖只剩 0.6", 0.6, r["weight_coverage"])
    check("其余四项都是 measured", 4,
          sum(1 for c in r["components"].values() if c["status"] == MEASURED))
    check("issues 明确说明 ocr 未计入", True,
          any("ocr 项未计入总分" in s for s in r["issues"]))

    # 总分必须 = 已测四项的加权平均（分母 0.6，不是 1.0）
    手算 = round(
        sum(c["weight"] * c["value"] for c in r["components"].values()
            if c["status"] == MEASURED) / 0.6, 4
    )
    check("总分按已测项重新归一化", 手算, r["score"])

    print()
    print(f"  实际输出：score={r['score']}  level={r['level']}  coverage={r['weight_coverage']}")
    for k, c in r["components"].items():
        print(f"    {k:<9} {str(c['value']):<8} {c['status']:<12} {c['detail']}")

    # ---------------- 场景 B：引擎给了置信度 ----------------
    blocks_b = MinerUAdapter(version_id="ver-b").to_blocks(add_confidence(load_raw(), 0.9))
    rb = score_blocks(blocks_b, page_count=2)

    print()
    print("=" * 72)
    print("场景 B：引擎提供了 confidence=0.9")
    print("=" * 72)
    check("ocr 变成 measured", MEASURED, rb["components"]["ocr"]["status"])
    check("权重全覆盖 1.0", 1.0, rb["weight_coverage"])
    check("ocr 得分 = 0.9/0.85 封顶 1.0", 1.0, rb["components"]["ocr"]["value"])
    check("总分高于场景 A", True, rb["score"] > r["score"])

    # ---------------- 场景 C：置信度很低 ----------------
    blocks_c = MinerUAdapter(version_id="ver-c").to_blocks(add_confidence(load_raw(), 0.4))
    rc = score_blocks(blocks_c, page_count=2)

    print()
    print("=" * 72)
    print("场景 C：引擎自己都没把握（confidence=0.4）")
    print("=" * 72)
    check("ocr 得分明显偏低", True, rc["components"]["ocr"]["value"] < 0.5)
    check("issues 提示识别置信度偏低", True,
          any("识别置信度偏低" in s for s in rc["issues"]))

    # ---------------- 场景 D：空结果 ----------------
    print()
    print("=" * 72)
    print("场景 D：什么都没解析出来")
    print("=" * 72)
    rd = score_blocks([], page_count=3)
    check("level=empty", "empty", rd["level"])
    check("score=0", 0.0, rd["score"])
    check("issue 说明没有内容块", True, any("没有解析出任何内容块" in s for s in rd["issues"]))

    print()
    print("=" * 72)
    print(f"通过 {passed} 项 [OK] ｜ 失败 {failed} 项 [!!]")
    print("=" * 72)

    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
