"""F-01 验收：故意喂错数据，看四个模型能不能拦住。

跑法（**必须在项目根目录**）：
    python -m tests.test_models

判定标准：全 [OK] = 所有错误都被按预期拦住。出现任何 [!!] 说明规矩写漏了，得改 models.py。

注：输出一律用 ASCII 标记，不用 emoji —— Windows 控制台默认 GBK，
输出一旦被重定向（CI、日志文件）emoji 就会让程序直接崩。
"""

import sys

from pydantic import ValidationError

from backend.core.enums import (
    BlockType,
    EvidenceSource,
    FindingEngine,
    RuleEngine,
    RuleScope,
    Severity,
)
from backend.core.models import Block, Chunk, Evidence, Finding, Rule

# 统一输出编码，避免「在我机器上能跑，换个终端就乱码」。
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

passed = 0      # 该通过且通过了
blocked = 0     # 该拦住且拦住了
failed = 0      # 判断错（该过的被拦 / 该拦的溜了）


def check(说明, 应该通过, 模型, 字段):
    """造一条数据：该通过就得通过，该拦住就得拦住，否则都算失败"""
    global passed, blocked, failed
    try:
        模型(**字段)
        if 应该通过:
            print(f"  [OK] {说明:<28} -> 通过")
            passed += 1
        else:
            print(f"  [!!] {说明:<28} -> 没拦住！这是漏网之鱼")
            failed += 1
    except ValidationError as e:
        err = e.errors()[0]
        位置 = ".".join(str(x) for x in err["loc"])
        if not 应该通过:
            print(f"  [OK] {说明:<28} -> 被拦住：{位置}（{err['type']}）")
            blocked += 1
        else:
            print(f"  [!!] {说明:<28} -> 本该通过却被拦：{位置}（{err['type']}）")
            failed += 1


print("=" * 68)
print("Block —— 文档切开的最小一块")
print("=" * 68)

check("① 规规矩矩写完整", True, Block, dict(
    id="b-001", version_id="v-001", idx=0, type=BlockType.TEXT,
    text="甲方未在约定期限内支付款项", page=7,
    bbox=[0.12, 0.31, 0.88, 0.35], raw_bbox=[86, 220, 630, 252],
))

check("② bbox 只给 3 个数字", False, Block, dict(
    id="b-002", version_id="v-001", idx=1, type=BlockType.TEXT,
    text="缺一个坐标", page=7,
    bbox=[0.12, 0.31, 0.88], raw_bbox=[86, 220, 630, 252],
))

check("③ 页码写成 0", False, Block, dict(
    id="b-003", version_id="v-001", idx=2, type=BlockType.TEXT,
    text="页码从 1 开始", page=0,
    bbox=[0.12, 0.31, 0.88, 0.35], raw_bbox=[86, 220, 630, 252],
))

check("④ type 直接写中文'表格'", False, Block, dict(
    id="b-004", version_id="v-001", idx=3, type="表格",
    text="不按清单来", page=7,
    bbox=[0.12, 0.31, 0.88, 0.35], raw_bbox=[86, 220, 630, 252],
))

print()
print("=" * 68)
print("Chunk —— 几块拼起来的一段语义")
print("=" * 68)

check("⑤ 规规矩矩写完整", True, Chunk, dict(
    id="c-001", version_id="v-001", block_ids=["b-001"],
    text="3.2.1 违约责任 甲方未在约定期限内支付款项",
    section_path="3.2.1 违约责任", page=7,
    bbox=[0.12, 0.28, 0.88, 0.35], char_span=(12450, 13002),
    tokens=18, index_in_doc=33,
))

check("⑥ 缺 section_path", False, Chunk, dict(
    id="c-002", version_id="v-001", block_ids=["b-001"],
    text="不知道自己属于哪一节", page=7,
    bbox=[0.12, 0.28, 0.88, 0.35], char_span=(12450, 13002),
    tokens=18, index_in_doc=34,
))

print()
print("=" * 68)
print("Evidence —— 从原文摘出来的原话")
print("=" * 68)

check("⑦ 规规矩矩写完整", True, Evidence, dict(
    id="e-001", chunk_id="c-001",
    quote="甲方未在约定期限内支付款项", page=7,
    bbox=[0.12, 0.31, 0.88, 0.35], char_span=(12450, 13002),
    retrieval_score=0.87, source=EvidenceSource.DOCUMENT,
))

check("⑧ quote 是空字符串", False, Evidence, dict(
    id="e-002", chunk_id="c-001", quote="", page=7,
    bbox=[0.12, 0.31, 0.88, 0.35], char_span=(12450, 13002),
    retrieval_score=0.87, source=EvidenceSource.DOCUMENT,
))

check("⑨ source 写成 'kb law'", False, Evidence, dict(
    id="e-003", chunk_id="c-001", quote="来个带空格的", page=7,
    bbox=[0.12, 0.31, 0.88, 0.35], char_span=(12450, 13002),
    retrieval_score=0.87, source="kb law",
))

print()
print("=" * 68)
print("Finding —— 一条审核意见")
print("=" * 68)

check("⑩ 规规矩矩写完整", True, Finding, dict(
    id="f-001", task_id="t-001", rule_id="CON-007",
    title="缺少违约责任条款", content="第三章未见任何关于违约责任的约定",
    severity=Severity.BLOCKING, engine=FindingEngine.RULE, confidence=1.0,
    evidence_ids=["e-001"],
    locator={"page": 7, "bbox": [0.12, 0.31, 0.88, 0.35], "chunk_id": "c-001"},
))

check("⑪ severity 拼成 bloking", False, Finding, dict(
    id="f-002", task_id="t-001", rule_id="CON-007",
    title="拼错的话", content="少了一个 c",
    severity="bloking", engine=FindingEngine.RULE, confidence=1.0,
    evidence_ids=["e-001"], locator={"page": 7},
))

check("⑫ confidence 写成 1.5", False, Finding, dict(
    id="f-003", task_id="t-001", rule_id="CON-007",
    title="把握超过 100%", content="不可能超过 1",
    severity=Severity.MAJOR, engine=FindingEngine.LLM, confidence=1.5,
    evidence_ids=["e-001"], locator={"page": 7},
))

check("⑬ 没有证据就下结论", False, Finding, dict(
    id="f-004", task_id="t-001", rule_id="CON-007",
    title="空口无凭", content="少了 evidence_ids",
    severity=Severity.MAJOR, engine=FindingEngine.LLM, confidence=0.6,
    locator={"page": 7},
))

print()
print("=" * 68)
print("Rule —— 一条审核规则")
print("=" * 68)

check("⑭ 规规矩矩写完整", True, Rule, dict(
    id="r-001", scope=RuleScope.GLOBAL, code="CON-007",
    name="违约责任条款缺失", description="合同正文必须包含违约责任章节",
    engine=RuleEngine.MISSING, severity=Severity.BLOCKING,
    doc_types=["contract"],
    params={"keywords": ["违约责任", "违约金"]},
    message_template="未检测到违约责任相关条款",
    remediation="建议补充 3.x 违约责任章节，明确违约金比例与上限",
    created_by="u-001",
))

check("⑮ code 写成小写 con-007", False, Rule, dict(
    id="r-002", code="con-007", name="业务码写成小写", description="规矩里要求大写",
    engine=RuleEngine.MISSING, severity=Severity.MAJOR, doc_types=["contract"],
    message_template="x", remediation="y", created_by="u-001",
))

# ------------------------------------------------------------------ 收尾总结

print()
print("=" * 68)
print(f"该通过的：{passed} 项 [OK] ｜ 该拦住的：{blocked} 项 [OK] ｜ 判断失误：{failed} 项 [!!]")
print("=" * 68)

if failed:
    print("\n有漏网之鱼，回去改 backend/core/models.py。")
    sys.exit(1)

print("\n全部符合预期。下面演示一次「从意见追回原文」：\n")

block = Block(
    id="b-100", version_id="v-001", idx=0, type=BlockType.TEXT,
    text="甲方未在约定期限内支付款项，每日按万分之五支付违约金。", page=7,
    bbox=[0.12, 0.31, 0.88, 0.35], raw_bbox=[86, 220, 630, 252],
)
chunk = Chunk(
    id="c-100", version_id="v-001", block_ids=[block.id], text=block.text,
    section_path="3.2.1 违约责任", page=7,
    bbox=block.bbox, char_span=(12450, 13002), tokens=24, index_in_doc=33,
)
evidence = Evidence(
    id="e-100", chunk_id=chunk.id,
    quote="甲方未在约定期限内支付款项", page=7,
    bbox=chunk.bbox, char_span=(12450, 13002),
    retrieval_score=0.91, source=EvidenceSource.DOCUMENT, verified=True,
)
finding = Finding(
    id="f-100", task_id="t-001", rule_id="CON-007",
    title="违约责任条款可能缺失", content="建议在 3.2.1 补充明确的违约责任约定",
    severity=Severity.BLOCKING, engine=FindingEngine.LLM, confidence=0.72,
    evidence_ids=[evidence.id],
    locator={"page": chunk.page, "bbox": chunk.bbox, "chunk_id": chunk.id},
    rationale="相邻条款仅提及付款义务，未见违约金比例的上限约定。",
    llm_model="deepseek-chat", prompt_version="v1",
)

print(f"  一条意见： {finding.title}")
print(f"  严重等级： {finding.severity}   把握：{finding.confidence}")
print(f"  它的证据： {finding.evidence_ids[0]}")
print(f"  证据原文： 「{evidence.quote}」")
print(f"  原文在哪： 第 {finding.locator['page']} 页，坐标 {finding.locator['bbox']}")
print()
print("  追溯链条： Finding → Evidence → Chunk → Block → 页面坐标")
print("             ↑ 这就是为什么每条结论都必须带 bbox：没有它就没法高亮给人看。")
