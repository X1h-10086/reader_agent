# M5 · LLM 审核与证据校验（Semantic Audit & Grounding）

> **职责**：对无法用规则判定的语义型条款做判定，并**用工程手段把幻觉率压到可用水平**。
> **对应需求**：R-09/R-11/R-12/R-13（语义判定、多文档、证据可溯）
> **关键词**：结构化输出、证据强制、NLI 复检、自一致性、置信度、预算熔断

---

## 1. 设计前提：LLM 会犯错，所以要"围起来用"

LLM 在文档审核中的三类典型错误：

| 错误 | 例子 | 防御 |
| --- | --- | --- |
| **编造位置** | 说"第 5.2 条违反…"但文档没有该条 | 编号/坐标回原文校验（本节 §3.2） |
| **编造内容** | 引用一段文档里没有的原文 | `char_span` / 子串精确匹配校验 |
| **过度解读** | 把中性表述判成重大风险 | 低置信度路由到人工 + 评测集调阈值 |

**一句话原则：LLM 只做"判断"，不做"陈述事实"。** 所有事实（条款原文、金额、日期、页码）必须来自检索结果并由程序校验。

---

## 2. 单次审核调用的输入编排

```
┌──────────────────── Prompt 组装（顺序有讲究）────────────────────┐
│ ① System：角色 + 铁律（不许编造、必须引用、不确定说不确定）      │
│ ② Rule：这条规则要检查什么、判定标准、严重级别定义              │
│ ③ DocumentSlice：候选 chunk（带 [chunk_id] 前缀标识）            │
│ ④ Knowledge（可选）：法条/模板（带 [kb:来源] 前缀）              │
│ ⑤ Few-shot：1~2 个正反例（JSON 格式样例）                        │
│ ⑥ 输出格式：严格 JSON Schema                                     │
│ ⑦ 自检清单：输出前请确认 quote 与原文逐字一致                    │
└─────────────────────────────────────────────────────────────────┘
```

### 2.1 结构化输出（用 Pydantic，不要自己解析字符串）

```python
class LlmFinding(BaseModel):
    rule_code: str
    hit: bool                              # 是否命中
    severity: Literal["blocking","major","minor","advice"]
    confidence: float = Field(ge=0, le=1)
    title: str
    content: str
    remediation: str
    evidence: list[LlmEvidence]            # ★ 至少 1 条，否则下游直接丢弃
    rationale: str                         # 判定理由（给人看的推理摘要）

class LlmEvidence(BaseModel):
    chunk_id: str                          # ★ 必须是给定候选里的 id
    quote: str                             # ★ 必须与原文逐字一致
    source: Literal["document","kb"]
    kb_id: str | None
```

用 `llm.with_structured_output(LlmFinding)` + 失败重试（含"格式纠正"二次提示）。
**成本提示**：`temperature=0`、`max_tokens` 限制、`seed` 固定（若 API 支持）——一切为了可复现。

---

## 3. 反幻觉四道防线（本模块的核心资产）

### 3.1 防线一：候选封闭
只把 `[chunk_id]` 候选放进 Prompt，并要求 `quote` 必须标注来源 id。**超出候选范围的 id 直接判错**。

### 3.2 防线二：机械校验（毫秒级，零成本）

```python
def verify(ev: LlmEvidence, chunks: dict) -> VerifyResult:
    c = chunks.get(ev.chunk_id)
    if not c:                          return VerifyResult(False, "chunk_id 不存在")
    if ev.quote not in c.text:         return VerifyResult(False, "quote 不在原文")
    if len(ev.quote) < 8:              return VerifyResult(False, "摘录过短")
    return VerifyResult(True, None, locator=c.locator)
```

> 这一步能干掉**绝大多数**编造。它是整个系统性价比最高的 20 行代码。

### 3.3 防线三：语义复检（NLI / 二次判断）
对高等级意见（`blocking/major`）再跑一次轻量调用：
> "以下原因是否**确实由**该引文支持？回答 支持 / 不支持 / 不足以下结论。"

返回"不支持/不足" → 降级为 `minor` 或直接丢弃。成本只增加约 15%，却显著降低误报。

### 3.4 防线四：自一致性与低置信路由
- 关键规则 **同温度跑 2 次**，结论不一致 → 置信度打折（`conf × 0.7`）并标记待人工；
- 最终按照 M6 的置信度闸门路由：`≥0.85 自动通过 / 0.5~0.85 待人工 / <0.5 抑制`。

---

## 4. 工具调用（Tool Use）

LLM 不应心算。注册以下工具，让它在需要时调用：

| 工具 | 用途 | 是否必须 |
| --- | --- | --- |
| `calculator(expr)` | 金额合计、税率、比例、日期差 | ★ 必须（数值结论由此产出） |
| `search_in_doc(query, filters)` | 自主补充检索（Agentic RAG） | 推荐 |
| `get_section(section_id)` | 拉取整节上下文 | 推荐 |
| `lookup_kb(query, domain)` | 查法规/制度 | 视规则而定 |

```python
@tool
def calculator(expr: str) -> str:
    """安全求值：仅允许数学表达式与日期差函数"""
    return safe_eval(expr)   # 白名单 AST 解析，禁止 eval/exec 裸调用
```

> **安全红线**：工具必须是白名单表达式或固定函数，绝不能让 LLM 传任意代码执行。

---

## 5. 成本控制三板斧

| 手段 | 效果 |
| --- | --- |
| **两阶段漏斗**：先用小模型/Embedding 筛掉 80% 无关候选，再让大模型判定 | 省 50%~70% |
| **结果缓存**：`(doc_version + rule_version + prompt_version)` 做键 | 重审近乎零成本 |
| **预算熔断**：单任务 token 上限，超限返回已完成部分并告警 | 防止失控账单 |

每个审核节点必须写入 `TraceStep`：输入摘要、输出摘要、tokens、耗时、模型与 prompt 版本。**没有 trace 的 LLM 调用等于没有发生过**——出问题时你连复盘都做不了。

---

## 6. 多文档交叉审核（P1）

对"主合同 vs 附件""招标文件 vs 投标文件"类需求：

1. 两文档分别走 M1/M2；
2. 构造对齐关系（同一 `rule_code` 下各自检索证据）；
3. 单次调用同时喂两份证据包，要求输出**差异清单**（含两边 quote 与 locator）；
4. 必须在结论里体现"哪边缺什么"，禁止笼统说"不一致"。

---

## 7. 输入 / 输出契约

| 项 | 内容 |
| --- | --- |
| 输入 | `Rule(engine=llm)` + `EvidencePack`(M4) + `doc_type` + 预算上下文 |
| 输出 | `Finding[]`（`engine="llm"`，带已校验 `Evidence` 与 `confidence`） |
| SLO | 单规则 ≤ 4s（含复检）；单任务总 LLM 调用次数可控（建议上限 ≤ 30 次） |

---

## 8. 单元验收（DoD）

- [ ] 故意让 Prompt 面对一个文档中不存在的条款，系统**不会**输出该意见（或 `evidence` 校验失败被丢弃）
- [ ] 所有通过校验的意见，`quote` 在原文中用 `Ctrl+F` 能一字不差搜到
- [ ] `confidence < 0.5` 的意见不会出现在最终报告中
- [ ] 同一任务重复执行两次，关键结论集合重合度 ≥ 90%
- [ ] 每个节点有 TraceStep，可回看当时的 prompt 版本与 token 消耗

---

## 9. 常见坑

| 坑 | 表现 | 解法 |
| --- | --- | --- |
| 让 LLM 自己给页码坐标 | 坐标全是假的 | 坐标只能由程序从 locator 反查，禁止模型输出 |
| Prompt 塞满全部候选 | 注意力稀释 + 超预算 | top_k ≤ 8，先 rerank |
| 温度 > 0 | 结果飘 | 固定 0；需要多样性时只对"改写建议"开温度 |
| 只测正面样例 | 上线才发现误报一堆 | 评测集必须含**负样例**（正确文档期望零命中） |
| 忽略负样例 | precision 极低 | 这是新手最常犯的错，务必一开始就埋负样例 |

---

## 10. 学习对应

对应学习路线 **阶段 4（LLM 接入与反幻觉）**。强烈建议做一个破坏性实验：
> 把同一份文档的问题连续问模型 3 次，记录它给出的引文，然后用字符串比对照妖镜去校验——**你会亲眼看到幻觉率有多高**，
> 也就会明白本节四道防线为什么一条都不能省。
