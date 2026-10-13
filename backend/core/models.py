"""backend/core/models.py —— 全系统四条核心数据的定义

对应文档：docs/03 §2.1 Block / §2.2 Chunk / §2.4 Evidence / §2.5 Finding

它只负责一件事：**任何数据想进系统，先过这里；规矩不对，当场拦下。**

这个文件只 import 了标准库和 pydantic —— 没有 Web 框架、没有数据库。
这样网站能用它，命令行能用它，测试也能用它。

------------------------------------------------------------------
本文件相对 docs/03 做的 4 处「收口」，全部事后回写进文档，不偷偷改：
1. Evidence.source 的 "kb law" → kb_law（空格进不了 URL 和数据库）
2. 契约里写 str 的枚举型字段（Block.type / Finding.severity 等），这里用枚举类接收。
   枚举是 str 的子类，所以不破坏契约，反而防止了拼错。
3. bbox 一律加 min_length=4, max_length=4。
   ★ 这正是「Pydantic 只拦你写明的规矩」的活例子：不写这一句，传 3 个数字它也放行。
4. Finding.created_at 给了默认值 datetime.now()，省得每次构造都手写时间。
------------------------------------------------------------------
"""

from datetime import datetime

from pydantic import BaseModel, Field

from .enums import (
    BlockType,
    EvidenceSource,
    FindingEngine,
    FindingStatus,
    RuleEngine,
    RuleScope,
    Severity,
)


# ------------------------------------------------------------------ bbox

# 坐标统一：归一化到 0~1 的 [x0, y0, x1, y1]，避免不同分辨率下缩放错位。
# 这是全系统反复出现的一个约束，抽出来复用，防止每个模型各写一遍写漏。
Bbox = list[float]


def _bbox_field(**kwargs):
    """生成一个「必须是 4 个数字」的坐标字段"""
    return Field(..., min_length=4, max_length=4, **kwargs)


# ------------------------------------------------------------------ M1 产出

class Block(BaseModel):
    """文档被切开后的一小块。

    对应 M1（MinerU 解析）的输出，**全链路可信的基石**：
    后面所有"原文在哪"的高亮，追根溯源都追到它身上。
    """

    id: str
    version_id: str                      # 属于文档的哪个版本
    idx: int                             # 阅读顺序，从 0 开始
    type: BlockType                      # 这一块是标题/正文/表格/页眉...
    text: str
    page: int = Field(..., ge=1)         # ge=1 → 页码从 1 开始，给 0 就报错
    bbox: Bbox = _bbox_field()           # 归一化坐标 [x0, y0, x1, y1]
    raw_bbox: list[float]                # 原始像素坐标，排查对不上时用
    char_span: tuple[int, int] | None = None   # 它在全文里第几个字符到第几个字符
    level: int | None = Field(default=None, ge=1, le=6)   # 标题层级 1~6，正文为 None
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)  # OCR/表格识别的把握
    meta: dict = Field(default_factory=dict)  # 表格 HTML、公式 LaTeX 等附件信息


# ------------------------------------------------------------------ M2 产出

class Chunk(BaseModel):
    """几块 Block 拼起来的一段完整语义。

    为什么要拼：单独一个句子常常缺上下文。
    所以每个 Chunk 都带着 section_path（如 "3.2.1 违约责任"），供切片推理和喂养参考。
    """

    id: str
    version_id: str
    block_ids: list[str]                 # 来源，用于从 Chunk 反查回 Block
    text: str
    section_path: str                    # "3.2.1 违约责任"
    page: int = Field(..., ge=1)
    bbox: Bbox = _bbox_field()           # 合并后的包围盒：能包住所有来源 block
    char_span: tuple[int, int]
    tokens: int                          # 这段多少个 token，控制别超模型窗口
    index_in_doc: int


# ------------------------------------------------------------------ M4/M5 产出

class Evidence(BaseModel):
    """证据：从原文或知识库里摘出来的**原话** + 它的位置。

    铁律：quote 必须是逐字摘录，改一个字就是伪造。
    """

    id: str
    chunk_id: str | None
    quote: str = Field(..., min_length=1)  # 空字符串不算证据
    page: int = Field(..., ge=1)
    bbox: Bbox = _bbox_field()
    char_span: tuple[int, int]
    retrieval_score: float = Field(..., ge=0.0, le=1.0)   # 检索打的分
    source: EvidenceSource                                # 来自文档还是知识库
    verified: bool = False            # ★ 是否通过"回原文比对"校验（M5 的活）
    verify_reason: str | None = None


# ------------------------------------------------------------------ M3/M5/M7 产出

class Finding(BaseModel):
    """审核意见：一条结论 —— 什么问题、多严重、多大把握、证据在哪。

    规则、大模型、人工，三个来源产出的都是同一种 Finding，
    这样它们在下游（报告、台账、评测）里能被同一个口径处理。
    """

    id: str
    task_id: str
    rule_id: str
    title: str
    content: str                        # 给人看的意见正文
    severity: Severity                  # 等级：阻断/严重/一般/建议
    engine: FindingEngine               # 谁产出的：规则 / 大模型 / 人工
    confidence: float = Field(..., ge=0.0, le=1.0)
    evidence_ids: list[str]             # 指向 Evidence 的 id
    locator: dict                       # {page, bbox, chunk_id} 前端高亮直接消费
    status: FindingStatus = FindingStatus.AUTO
    rationale: str | None = None        # 判定理由（尤其大模型的推理摘要）
    llm_model: str | None = None
    prompt_version: str | None = None
    created_at: datetime = Field(default_factory=datetime.now)


# ------------------------------------------------------------------ M3 产出

class Rule(BaseModel):
    """一条审核规则。

    规则是「人写的、机器执行的确定性判断」，不经过大模型，所以成本几乎为零、
    结果可复现。它也是整个系统里用户最能自己掌控的部分（F-10 会做成可在线编辑）。
    """

    id: str
    scope: RuleScope = RuleScope.GLOBAL   # 全局规则，还是只针对某一份文档
    document_id: str | None = None        # scope=document 时必填
    code: str = Field(..., pattern=r"^[A-Z]{2,6}-\d{3}$")   # 业务码，形如 CON-001
    name: str
    description: str
    enabled: bool = True
    engine: RuleEngine                    # 用哪种引擎判定
    severity: Severity                    # 命中后给出的等级
    doc_types: list[str]                  # 只对这些文档类型生效
    params: dict = Field(default_factory=dict)      # 引擎参数：pattern / keywords / formula...
    retrieve_required: bool = False       # 是否需要先检索证据（决定要不要走 RAG）
    kb_sources: list[str] = Field(default_factory=list)
    message_template: str                 # 命中时给人的文案模板
    remediation: str                      # 修改建议模板
    version: int = 1                      # ★ 规则也有版本，否则结果无法复现
    created_by: str
    hit_count: int = 0                    # 命中统计，用于规则治理（长期零命中应下线）


__all__ = ["Block", "Chunk", "Evidence", "Finding", "Rule"]
