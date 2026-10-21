"""backend/core/selfcheck.py —— CAP-CORE-01「数据契约自检」的实现。

它验证的规矩和 tests/test_models.py 是**同一套**（都来自 backend/core/models.py），
区别只是：
    tests/test_models.py  → 打印给人看（命令行）
    这个文件             → 返回数据给探针台显示（浏览器）

⚠️ 以后每往 models.py 加一条数据结构，这里也要补一条用例，
否则探针台会给你一个「天下太平」的假象 —— 那比没有探针台更危险。
"""

from __future__ import annotations

from pydantic import ValidationError

from backend.core.enums import EvidenceSource, FindingEngine, Severity
from backend.core.models import Evidence, Finding


def run() -> dict:
    """造 2 条对的 + 3 条错的，返回统计与逐条明细。"""

    明细: list[dict] = []

    # ① 对的：一条规规矩矩的审核意见，应当通过
    try:
        Finding(
            id="f-001",
            task_id="task-001",
            rule_id="r-001",
            title="缺少违约责任条款",
            content="第三章未见任何关于违约责任的约定",
            severity=Severity.BLOCKING,
            engine=FindingEngine.RULE,
            confidence=0.95,
            evidence_ids=["ev-001"],
            locator={"page": 3, "bbox": [0.10, 0.20, 0.90, 0.30], "chunk_id": "ck-012"},
        )
        明细.append({"用例": "规规矩矩写完整", "预期": "通过", "实际": "通过"})
    except ValidationError as e:
        明细.append({"用例": "规规矩矩写完整", "预期": "通过", "实际": f"被拦住：{_定位(e)}"})

    # ② 对的：一条规规矩矩的证据，应当通过
    try:
        Evidence(
            id="ev-001",
            chunk_id="ck-012",
            quote="甲方未按约定时间支付货款的，应按日千分之三支付违约金",
            page=3,
            bbox=[0.10, 0.20, 0.90, 0.30],
            char_span=(120, 156),
            retrieval_score=0.87,
            source=EvidenceSource.DOCUMENT,
        )
        明细.append({"用例": "证据四要素齐全", "预期": "通过", "实际": "通过"})
    except ValidationError as e:
        明细.append({"用例": "证据四要素齐全", "预期": "通过", "实际": f"被拦住：{_定位(e)}"})

    # ③ 错的：severity 少打一个字母 c
    try:
        Finding(
            id="f-002", task_id="task-001", rule_id="r-001",
            title="发票金额与合同不一致", content="发票金额 12,000 元，合同约定 10,000 元",
            severity="bloking",                 # ← 故意的，少一个 c
            engine=FindingEngine.RULE, confidence=0.9,
            evidence_ids=[], locator={},
        )
        明细.append({"用例": "severity 拼成 bloking", "预期": "拦住", "实际": "放行了 ← 漏网之鱼"})
    except ValidationError as e:
        明细.append({"用例": "severity 拼成 bloking", "预期": "拦住", "实际": f"拦住：{_定位(e)}"})

    # ④ 错的：confidence 写成中文
    try:
        Finding(
            id="f-003", task_id="task-001", rule_id="r-001",
            title="把握很高", content="x",
            severity=Severity.MAJOR, engine=FindingEngine.RULE,
            confidence="很高",                  # ← 故意的，这里要数字
            evidence_ids=[], locator={},
        )
        明细.append({"用例": "confidence 写成中文", "预期": "拦住", "实际": "放行了 ← 漏网之鱼"})
    except ValidationError as e:
        明细.append({"用例": "confidence 写成中文", "预期": "拦住", "实际": f"拦住：{_定位(e)}"})

    # ⑤ 错的：bbox 只给 3 个数字（docs/03 §2.8 收口 #3 的活例子）
    try:
        Evidence(
            id="ev-002", chunk_id="ck-013", quote="一段原文", page=1,
            bbox=[0.10, 0.20, 0.30],           # ← 故意的，少一个数
            char_span=(0, 6), retrieval_score=0.5, source=EvidenceSource.DOCUMENT,
        )
        明细.append({"用例": "bbox 只给 3 个数字", "预期": "拦住", "实际": "放行了 ← 漏网之鱼"})
    except ValidationError as e:
        明细.append({"用例": "bbox 只给 3 个数字", "预期": "拦住", "实际": f"拦住：{_定位(e)}"})

    符合预期 = sum(1 for d in 明细 if d["实际"] == "通过" or d["实际"].startswith("拦住："))
    return {
        "结论": "全部符合预期" if 符合预期 == len(明细) else f"{len(明细) - 符合预期} 条漏网之鱼，去改 models.py",
        "符合预期": f"{符合预期}/{len(明细)}",
        "明细": 明细,
        "说明": "规矩全部来自 backend/core/models.py，与 tests/test_models.py 同源",
    }


def _定位(exc: ValidationError) -> str:
    """把报错压缩成「字段名（类型）」——就是你在动作 2 见过的那种读法。"""
    err = exc.errors()[0]
    字段 = ".".join(str(x) for x in err["loc"])
    return f"{字段}（{err['type']}）"
