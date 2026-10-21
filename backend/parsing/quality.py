"""解析质量评分（docs M1 §3.4）。

原则：不追求完美，用几个便宜的启发式信号加权即可。

两条额外的规矩：

1. **必须给分项明细**。用户问"凭什么说我文档质量差"时，要能答出是哪一项拖低的。
2. **没有数据就说"没有数据"，不能假装满分**。
   比如解析引擎没给置信度时，ocr 这一项标成 unavailable 并从总分里剔除，
   而不是拿一个默认的 1.0 充数 —— 那会让总分虚高，掩盖真正的问题。
"""

from __future__ import annotations

import re

from backend.core.models import Block

# 各分项权重，加起来必须等于 1.0
WEIGHTS: dict[str, float] = {
    "ocr": 0.4,        # 识别置信度 —— 权重最高，因为它是所有下游的地基
    "outline": 0.2,    # 章节结构是否识别出来
    "density": 0.2,    # 每页文字量是否在合理区间
    "table": 0.1,      # 表格是否结构化
    "language": 0.1,   # 语种是否符合预期
}

# 低于这个分数 → 提示"文档质量差，建议人工确认"（M1 §3.3 的降级触发线）
LOW_QUALITY_THRESHOLD = 0.6

MEASURED = "measured"          # 这一项有真实数据
UNAVAILABLE = "unavailable"    # 这一项没有数据，不参与总分

_CJK = re.compile(r"[\u4e00-\u9fff]")


def _confidence_provided(b: Block) -> bool:
    """这个 block 的 confidence 是引擎给的，还是 Adapter 默认填的？"""
    return bool(b.meta.get("_adapter", {}).get("confidence_provided", True))


def score_blocks(
    blocks: list[Block],
    page_count: int,
    expected_lang: str = "zh",
) -> dict:
    """给一次解析结果打分（0~1），并给出分项明细与缺失说明。"""
    if not blocks:
        return {
            "score": 0.0,
            "level": "empty",
            "threshold": LOW_QUALITY_THRESHOLD,
            "weight_coverage": 0.0,
            "components": {},
            "issues": ["没有解析出任何内容块"],
        }

    components: dict[str, dict] = {}
    issues: list[str] = []

    # ---------------- ① 识别置信度 ----------------
    provided = [b.confidence for b in blocks if _confidence_provided(b)]
    if provided:
        avg_conf = sum(provided) / len(provided)
        value = round(min(1.0, avg_conf / 0.85), 4)     # 0.85 以上算满分
        components["ocr"] = {
            "weight": WEIGHTS["ocr"],
            "value": value,
            "status": MEASURED,
            "detail": f"平均识别置信度 {avg_conf:.2f}（{len(provided)}/{len(blocks)} 块提供了数值）",
        }
        if value < 0.8:
            issues.append(f"识别置信度偏低（{avg_conf:.2f}），可能是扫描件或字迹模糊")
    else:
        components["ocr"] = {
            "weight": WEIGHTS["ocr"],
            "value": None,
            "status": UNAVAILABLE,
            "detail": "引擎没有提供识别置信度 —— 这一项无法评估，已从总分中剔除",
        }
        issues.append("引擎未提供识别置信度：ocr 项未计入总分（宁可不给分，也不假装满分）")

    # ---------------- ② 章节结构 ----------------
    titles = [b for b in blocks if b.type.value == "title"]
    if titles:
        with_level = sum(1 for b in titles if b.level)
        outline = round(with_level / len(titles), 4)
        components["outline"] = {
            "weight": WEIGHTS["outline"],
            "value": outline,
            "status": MEASURED,
            "detail": f"{with_level}/{len(titles)} 个标题带层级",
        }
        if outline < 1.0:
            issues.append("部分标题没识别出层级，章节目录可能不完整")
    else:
        components["outline"] = {
            "weight": WEIGHTS["outline"],
            "value": 0.5,
            "status": MEASURED,
            "detail": "没有识别到任何标题（中性给 0.5）",
        }
        issues.append("没有识别到标题，文档可能缺少清晰的章节结构")

    # ---------------- ③ 文字密度 ----------------
    total_chars = sum(len(b.text) for b in blocks)
    per_page = total_chars / max(1, page_count)
    if per_page < 200:
        density = round(per_page / 200, 4)
        issues.append(f"每页仅 {per_page:.0f} 字符，可能有漏字（扫描件没走 OCR？）")
    elif per_page > 3000:
        density = round(3000 / per_page, 4)
        issues.append(f"每页 {per_page:.0f} 字符，密度异常高，可能多栏文字粘连")
    else:
        density = 1.0
    components["density"] = {
        "weight": WEIGHTS["density"],
        "value": density,
        "status": MEASURED,
        "detail": f"共 {total_chars} 字符 / {page_count} 页 = {per_page:.0f} 字符/页",
    }

    # ---------------- ④ 表格结构化 ----------------
    tables = [b for b in blocks if b.type.value == "table"]
    if tables:
        ok = sum(1 for b in tables if b.meta.get("html") or b.meta.get("latex"))
        table_score = round(ok / len(tables), 4)
        components["table"] = {
            "weight": WEIGHTS["table"],
            "value": table_score,
            "status": MEASURED,
            "detail": f"{ok}/{len(tables)} 个表格拿到了结构化内容",
        }
        if table_score < 1.0:
            issues.append("有表格没解析成结构化数据，数值类规则会失效")
    else:
        components["table"] = {
            "weight": WEIGHTS["table"],
            "value": 1.0,
            "status": MEASURED,
            "detail": "文档中没有表格",
        }

    # ---------------- ⑤ 语种 ----------------
    all_text = "".join(b.text for b in blocks)
    cjk_ratio = len(_CJK.findall(all_text)) / max(1, len(all_text))
    if expected_lang == "zh":
        language = 1.0 if cjk_ratio >= 0.2 else 0.4
        detail = f"中文字符占比 {cjk_ratio:.0%}"
    else:
        language = 1.0
        detail = "未做语种检测"
    components["language"] = {
        "weight": WEIGHTS["language"],
        "value": language,
        "status": MEASURED,
        "detail": detail,
    }
    if language < 1.0:
        issues.append(f"中文只占 {cjk_ratio:.0%}，确认文档语种是否符合预期")

    # ---------------- 汇总 ----------------
    # 只在「有数据的项」之间重新分配权重，而不是给缺失项记 0 分。
    # 否则"不知道"会被当成"很差"，同样是失真。
    measured = {k: c for k, c in components.items() if c["status"] == MEASURED}
    total_weight = round(sum(c["weight"] for c in measured.values()), 4)

    score = 0.0
    if total_weight > 0:
        score = round(
            sum(c["weight"] * c["value"] for c in measured.values()) / total_weight, 4
        )

    return {
        "score": score,
        "level": "low" if score < LOW_QUALITY_THRESHOLD else "good",
        "threshold": LOW_QUALITY_THRESHOLD,
        "weight_coverage": total_weight,      # 1.0 = 五项全有数据；0.6 = 缺了权重 0.4 的那项
        "components": components,
        "issues": issues,
    }
