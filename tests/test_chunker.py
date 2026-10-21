"""F-05 验收：章节树与结构优先切片（CAP-M2-01 / CAP-M2-02）。

判定标准：全 [OK]。

重点验四条硬规则：
    ① 章节层级正确（含「推不出来就记 None」）
    ② 禁止跨章节合并
    ③ 表格整块保留、不与正文混切
    ④ 每个 chunk 带 section_path 前缀

用法：
    python -m tests.test_chunker
"""

import sys

from backend.core.enums import BlockType
from backend.core.models import Block
from backend.representation.chunker import build_chunks
from backend.representation.section_tree import (
    build_section_tree,
    guess_level,
    iter_sections,
)

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

passed = 0
failed = 0


def check(说明: str, 期望, 实际) -> None:
    global passed, failed
    if 期望 == 实际:
        print(f"  [OK] {说明:<34} -> {实际!r}")
        passed += 1
    else:
        print(f"  [!!] {说明:<34} -> 期望 {期望!r}，实际 {实际!r}")
        failed += 1


def make_blocks(spec: list[tuple[str, str, int | None, int]]) -> list[Block]:
    """spec: [(type, text, level, page)] → Block[]（自动算 idx 与 char_span）"""
    blocks: list[Block] = []
    pos = 0
    for i, (type_name, text, level, page) in enumerate(spec):
        blocks.append(
            Block(
                id=f"b-{i:03d}",
                version_id="v1",
                idx=i,
                type=BlockType(type_name),
                text=text,
                page=page,
                bbox=[0.1, 0.1, 0.9, 0.2],
                raw_bbox=[10.0, 10.0, 90.0, 20.0],
                char_span=(pos, pos + len(text)),
                level=level,
                confidence=1.0,
                meta={},
            )
        )
        pos += len(text) + 1
    return blocks


def main() -> None:
    # ---------------- 基础样例 ----------------
    spec = [
        ("header", "机密 · 合同审核专用", None, 1),
        ("title", "3 责任", 1, 1),
        ("text", "本章约定双方在交付、验收与违约方面的责任。", None, 1),
        ("title", "3.2 验收", 2, 1),
        ("text", "甲方应在收到设备后十五个工作日内完成验收，逾期未提出异议视为验收合格。", None, 1),
        ("title", "3.3 违约责任", 2, 2),
        ("text", "乙方逾期交付的，每逾期一日按合同总价的千分之三支付违约金。", None, 2),
        ("table", "货款 10000", None, 2),
    ]
    blocks = make_blocks(spec)
    tree = build_section_tree(blocks)

    print("=" * 72)
    print("章节树（CAP-M2-01）")
    print("=" * 72)
    check("根节点下有 1 个一级章节", 1, len(tree.children))
    top = tree.children[0]
    check("一级标题 level=1", 1, top.level)
    check("一级下挂 2 个子章节", 2, len(top.children))
    check("子章节顺序 = 阅读顺序",
          ["3.2 验收", "3.3 违约责任"], [c.title for c in top.children])
    check("section_path 是完整路径", "3 责任 > 3.2 验收", top.children[0].path)
    check("根节点的正文是页眉（不在任何章节里）", 1, len(tree.blocks))

    print()
    print("=" * 72)
    print("层级推断：有编号才推断，没编号就记 None（不硬猜）")
    print("=" * 72)
    check("'3.1.2 xxx' → 三级", 3, guess_level("3.1.2 违约责任"))
    check("'3.2 xxx' → 二级", 2, guess_level("3.2 验收"))
    check("'第三章 xxx' → 一级", 1, guess_level("第三章 总则"))
    check("'一、xxx' → 一级", 1, guess_level("一、总则"))
    check("没有编号 → None", None, guess_level("其他约定"))

    uncertain = make_blocks([
        ("title", "其他约定", None, 1),
        ("text", "双方另行协商。", None, 1),
    ])
    u_tree = build_section_tree(uncertain)
    check("推不出层级的标题，level 记 None", None, u_tree.children[0].level)

    # ---------------- 切片 ----------------
    chunks = build_chunks(blocks, "v1")
    print()
    print("=" * 72)
    print("结构优先切片（CAP-M2-02）")
    print("=" * 72)
    check("chunk 总数（根 1 + 3.1 + 3.2 + 3.3正文 + 表格）", 5, len(chunks))
    check("index_in_doc 连续", list(range(5)), [c.index_in_doc for c in chunks])
    check("每个 chunk 都以 [章节路径] 开头", True,
          all(c.text.startswith("[") and "]" in c.text[:40] for c in chunks))

    # 禁止跨章节：每个 chunk 的所有块必须属于同一个 section
    owner: dict[str, str] = {}
    for node in iter_sections(tree):
        for b in node.blocks:
            owner[b.id] = node.path or "（未分章）"
    跨章节的 = [c for c in chunks if len({owner.get(i) for i in c.block_ids}) > 1]
    check("没有任何 chunk 跨章节", 0, len(跨章节的))

    # 表格整块保留
    table_chunk = [c for c in chunks if "b-007" in c.block_ids]
    check("存在表格 chunk", 1, len(table_chunk))
    check("表格 chunk 只有表格这一块", ["b-007"], table_chunk[0].block_ids)
    check("表格 chunk 的 section_path 正确", "3 责任 > 3.3 违约责任", table_chunk[0].section_path)

    # ---------------- 长章节二次切分 ----------------
    print()
    print("=" * 72)
    print("章节超长 → 滚动窗口二次切分（带重叠）")
    print("=" * 72)
    long_spec = [("title", "4 附则", 1, 1)] + [
        ("text", f"第{i}段：" + "字" * 100, None, 1) for i in range(1, 9)
    ]
    long_chunks = build_chunks(make_blocks(long_spec), "v1", max_chars=250, overlap=100)
    check("长章节被切成多片", True, len(long_chunks) > 1)
    有重叠 = any(
        set(long_chunks[i].block_ids) & set(long_chunks[i + 1].block_ids)
        for i in range(len(long_chunks) - 1)
    )
    check("相邻切片有重叠（上下文不断）", True, 有重叠)
    check("每一片仍控制在合理长度", True, all(c.tokens < 500 for c in long_chunks))
    check("每片都带同一章节前缀", True,
          all(c.section_path == "4 附则" for c in long_chunks))

    # ---------------- 无标题文档 ----------------
    print()
    print("=" * 72)
    print("没有标题的文档也能切")
    print("=" * 72)
    no_title = make_blocks([
        ("text", "没有标题的第一段。", None, 1),
        ("text", "第二段。", None, 1),
    ])
    nc = build_chunks(no_title, "v1")
    check("全部归入（未分章）", "（未分章）", nc[0].section_path)
    check("两块正文合成一个 chunk", 1, len(nc))

    # ---------------- 总结 ----------------
    print()
    print("=" * 72)
    print(f"通过 {passed} 项 [OK] ｜ 失败 {failed} 项 [!!]")
    print("=" * 72)

    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
