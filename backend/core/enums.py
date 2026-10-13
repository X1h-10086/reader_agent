"""backend/core/enums.py —— 全系统枚举的「单一来源」

对应文档：docs/04 目录结构 `backend/core/enums.py`（★ 枚举单一来源）

三条铁律（改这个文件之前先读一遍）：

1. 本文件只允许 import 标准库。**禁止出现 fastapi / sqlalchemy / requests 等第三方。**
   为什么：这是「食材的定义」。一旦它依赖 Web 框架，命令行脚本和单元测试就用不了它 ——
   在没装 fastapi 的机器上，`import backend.core.enums` 会直接报错，
   哪怕你只是想半夜跑 `python scan.py contracts/*.pdf` 扫本地文件。

2. 取值一律小写 + 下划线，禁止空格。
   （docs/03 里 Evidence.source 写的 "kb law" 在这里收口成 kb_law —— 空格进 URL/数据库是灾难。）

3. 新增取值必须同步回写 docs/03。两边不一致 = 约束失效 = 白白多一层复杂度。

为什么用 `str, Enum` 而不是纯 Enum：
这样每个成员既是枚举（能约束取值），又是一个真正的字符串（能直接拼字符串、写 JSON、存数据库），
省掉到处 `.value` 的麻烦。
"""

from enum import Enum


class StrValue(str, Enum):
    """所有枚举的基类：同时具备「枚举的可约束」和「字符串的好用」"""

    def __str__(self) -> str:
        # 不覆盖的话，str(Severity.BLOCKING) 会得到 "Severity.BLOCKING" 而不是 "blocking"
        return self.value

    @classmethod
    def values(cls) -> list[str]:
        """列出所有合法取值 —— 前端下拉框 / 文档生成都靠它"""
        return [m.value for m in cls]


# ---------------------------------------------------------------- 严重等级

class Severity(StrValue):
    """严重等级 —— 决定这条意见是否阻断流程。

    ⚠️ 等级 ≠ 置信度：一条把握只有 0.3 的意见，等级照样可以是 blocking（宁可错报不可放过）。
    取值来源：docs/03 §2.3 Rule.severity / §2.5 Finding.severity
    """

    BLOCKING = "blocking"   # 阻断：不改不能往下走（如缺少甲方主体）
    MAJOR = "major"         # 严重：明显违规，需人工确认
    MINOR = "minor"         # 一般：规范性问题
    ADVICE = "advice"       # 建议：可有可无的优化点


# ---------------------------------------------------------------- 文档结构

class BlockType(StrValue):
    """Block 的内容类型（MinerU 解析后给每一块贴的标签）

    取值来源：docs/03 §2.1 Block.type
    """

    TITLE = "title"
    TEXT = "text"
    TABLE = "table"
    FIGURE = "figure"
    FORMULA = "formula"
    CAPTION = "caption"
    HEADER = "header"    # 页眉 —— 跑规则时通常要跳过
    FOOTER = "footer"    # 页脚 —— 页码千万别参与数值校验


# ---------------------------------------------------------------- 引擎

class RuleEngine(StrValue):
    """规则的判定引擎 —— 对应 Rule.engine

    除了 LLM，其余六种都是确定性的：同样的输入必然同样的输出，成本几乎为零。
    取值来源：docs/03 §2.3
    """

    REGEX = "regex"                # 正则匹配
    DICT = "dict"                  # 关键词词典
    MISSING = "missing"            # 缺项检查：该有的话有没有
    NUMERIC = "numeric"            # 数值校验：总额 / 日期 / 阈值
    STRUCTURAL = "structural"      # 结构检查：章节完整性
    CONSISTENCY = "consistency"    # 一致性：前后是否矛盾
    LLM = "llm"                    # 交给大模型 —— 唯一的不确定性引擎


class FindingEngine(StrValue):
    """这条意见是谁产出的 —— 对应 Finding.engine

    注意和 RuleEngine 不是一回事：RuleEngine 描述「规则怎么算」，
    FindingEngine 描述「结论从哪来」。
    取值来源：docs/03 §2.5
    """

    RULE = "rule"     # 硬规则产出，confidence 恒为 1.0
    LLM = "llm"       # 大模型语义判定
    HUMAN = "human"   # 人工新增或修改


# ---------------------------------------------------------------- 证据与意见

class EvidenceSource(StrValue):
    """证据来自哪里 —— 对应 Evidence.source

    取值来源：docs/03 §2.4。文档里写作 "kb law"，此处统一收口成 kb_law。
    """

    DOCUMENT = "document"          # 被审文档自身
    KB_LAW = "kb_law"              # 知识库：法规
    KB_TEMPLATE = "kb_template"    # 知识库：标准模板
    KB_CASE = "kb_case"            # 知识库：历史案例


class FindingStatus(StrValue):
    """意见的生命周期 —— 对应 Finding.status

    流转：auto → confirmed / dismissed / modified，或 → pending_human 排队等人
    取值来源：docs/03 §2.5
    """

    AUTO = "auto"                    # 机器产出，还没人看过
    CONFIRMED = "confirmed"          # 人工确认：认可这条
    DISMISSED = "dismissed"          # 人工驳回：这是误报
    MODIFIED = "modified"            # 人工修改：结论对，但描述要改
    PENDING_HUMAN = "pending_human"  # 置信度太低，等待人工处理


# ---------------------------------------------------------------- 任务与规则

class TaskState(StrValue):
    """审核任务状态 —— 对应 AuditTask.state

    取值来源：docs/03 §2.7
    """

    RUNNING = "running"
    WAITING_HUMAN = "waiting_human"   # 卡在人工闸门（通常是 L 级问题）
    DONE = "done"
    FAILED = "failed"
    CANCELED = "canceled"


class RuleScope(StrValue):
    """规则作用范围 —— 对应 Rule.scope，支撑 R-04「文档级自定义规则」"""

    GLOBAL = "global"        # 全局：所有文档都适用
    DOCUMENT = "document"    # 文档级：只对指定 document_id 生效


# ---------------------------------------------------------------- 自检入口

__all__ = [
    "StrValue",
    "Severity",
    "BlockType",
    "RuleEngine",
    "FindingEngine",
    "EvidenceSource",
    "FindingStatus",
    "TaskState",
    "RuleScope",
]


if __name__ == "__main__":
    # 这个文件既是实现，也是自检脚本。跑法：
    #   cd d:/desktop/文档审核智能体
    #   python -m backend.core.enums
    import json

    print("① 合法取值一览：", Severity.values())
    print("② 当字符串直接用：", "这条意见等级是 " + Severity.BLOCKING)
    print("③ 写进 JSON：", json.dumps({"severity": Severity.BLOCKING}))

    print("④ 随便写一个不存在的值：", end=" ")
    try:
        Severity("fatal")          # 拼错 / 瞎编
    except ValueError as e:
        print("当场被拦住 →", str(e)[:80])
