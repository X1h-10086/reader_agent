# M6 · Agent 编排与人机闸门（Orchestration）

> **职责**：把 M1~M5 串成一个**可控、可中断、可回放、可增量重跑**的状态机。
> **对应需求**：R-03（人工随时介入）、R-04（实时重新审查）、项目文档 §Agent 编排
> **技术载体**：LangGraph `StateGraph` + `Checkpointer` + `interrupt`

---

## 1. 为什么需要显式编排

三种做法对比：

| 做法 | 优点 | 致命问题 |
| --- | --- | --- |
| 顺序脚本 `a→b→c` | 简单 | 无法并行、无法中断、无法断点续跑 |
| Celery 链式任务 | 可异步 | 状态散落各处，人工介入难，回放难 |
| **LangGraph 状态图（本项目选择）** | 状态集中、条件路由、断点、检查点 | 学习成本略高 |

关键判断标准就一句话：**你要不要"人在流程中间"？** 需要 → 必须状态机。本项目的 R-03 明确需要。

---

## 2. 图结构（与 [01-总体架构](../../docs/01-总体架构设计.md) §4 一致）

节点清单与职责：

| 节点 | 职责 | 失败策略 |
| --- | --- | --- |
| `ingest` | 落库存哈希、格式校验 | 终止 |
| `parse` | 调 M1 | 重试 1 次 → 降级 VLM → 仍失败则转人工 |
| `structure` | 调 M2 建树切片索引 | 重试 1 次 |
| `plan` | 加载 RuleSet，生成 `PlanItem[]`，估算预算 | 终止 |
| `rule_audit` | 调 M3（并行批执行） | 单规则失败不阻断整体，记 trace |
| `retrieve` | 调 M4，为语义规则准备证据包 | 失败则该规则跳过并标注 |
| `llm_audit` | 调 M5（并行 Map，每条规则一个分支） | 重试 2 次，仍失败丢弃该条 |
| `verify` | 证据机械校验 + NLI 复检 | — |
| `adjudicate` | 去重、冲突裁决、级别与置信度融合 | — |
| `confidence_gate` | 条件路由（自动 / 待人工 / 抑制） | — |
| `human_review` | `interrupt` 挂起，等待人工意见 | 超时策略：默认保持挂起 |
| `report` | 调 M6 报告生成 | 重试 1 次 |
| `persist` | 写库 + 写 trace + 更新规则命中统计 | — |

---

## 3. 三个关键机制的代码形态

### 3.1 状态与并行扇出

```python
graph = StateGraph(AuditState)
graph.add_node("plan", plan_node)
graph.add_node("rule_audit", rule_audit_node)
graph.add_node("retrieve",  retrieve_node)
graph.add_node("llm_audit", llm_audit_node)   # 内部 Send() 按 PlanItem 并行
graph.add_node("verify", verify_node)
graph.add_node("adjudicate", adjudicate_node)
graph.add_node("human_review", human_review_node)
graph.add_node("report", report_node)

graph.add_edge(START, "plan")
graph.add_conditional_edges("plan", route_engine, {"rule":"rule_audit", "semantic":"retrieve"})
graph.add_edge("retrieve", "llm_audit")
graph.add_edge(["rule_audit","llm_audit"], "verify")   # 汇合
graph.add_edge("verify", "adjudicate")
graph.add_conditional_edges("adjudicate", gate, {
    "auto": "report", "need_human": "human_review", "drop": "report"
})
graph.add_edge("human_review", "report")
graph.add_edge("report", "persist")
graph.add_edge("persist", END)
```

### 3.2 人工闸门（R-03 的落地）

```python
from langgraph.types import interrupt

def human_review_node(state: AuditState):
    pending = [f for f in state["findings"] if f["status"] == "pending_human"]
    ops = interrupt({"reason": "low_confidence", "findings": pending})   # ← 在此挂起
    state["human_ops"] = ops                                            # 恢复时注入
    return apply_ops(state, ops)
```

前端行为：WebSocket 收到 `need_human` → 页面弹出待确认列表 → 用户提交 → 调 `POST /tasks/{id}/resume` → 从检查点继续。
**注意 `Checkpointer` 必须用可持久化的实现（SQLite/Postgres），否则进程重启人类社会就丢了。**

### 3.3 增量重审（R-04 的落地）

用户新增/修改一条文档级规则时，不必全图重跑：

```python
# 只重跑受影响的语义规则分支
affected = [p for p in plan if p.rule_id in changed_rule_ids]
resume enhances: update_state(thread, {"rule_ids": affected})
```

更进一步：
- 解析层结果按 `version + file_hash` 缓存，永不再算；
- 索引按 `version + chunk_params` 缓存；
- LLM 结果按 `version + rule_version + prompt_version` 缓存。
→ 改动一条规则时，实际只花"那一条规则"的钱。

---

## 4. 预算与熔断

```python
class Budget(BaseModel):
    max_tokens: int = 200_000
    max_seconds: int = 300
    max_llm_calls: int = 30
```

每个 LLM 节点前置检查；超限则：
1. 记录 `TraceStep(error="BUDGET_EXCEEDED")`；
2. 已产出的 findings 照常出报告，并在报告顶部标注"本次审核未完整执行"；
3. 发送告警。

> **宁可出一份不完整的报告，也不要让用户等到超时或产生天价账单。**

---

## 5. 冲突裁决规则（adjudicate 节点）

当同一位置被多条规则/多次判定命中，或规则结论与 LLM 结论冲突：

| 情形 | 裁决 |
| --- | --- |
| 同一 chunk 同一 rule_code 重复 | 保留最高 severity，合并证据，去重 |
| 硬规则命中 vs LLM 说没问题 | **以硬规则为准**（确定性优先），LLM 意见降级为备注 |
| LLM 说有问题 vs 硬规则无命中 | 保留，但强制走人工闸门（conf × 0.8） |
| 两条 LLM 意见表述近似 | embedding 相似度 > 0.92 合并，保留更详细的那条 |
| 严重级别冲突 | 取高（宁严勿松），并在意见里注明存在不同判断 |

---

## 6. 输入 / 输出契约

| 项 | 内容 |
| --- | --- |
| 输入 | `AuditState`（见 01 §4） |
| 输出 | 全量 `Finding[]` + `TraceStep[]` + 报告句柄 |
| SLO | 100 页 + 60 条规则端到端 ≤ 120s；其中等待人工不计入 |

---

## 7. 单元验收（DoD）

- [ ] 低置信度任务会挂起而非自动出结论；提交人工意见后能**从断点继续**到报告
- [ ] 进程重启后未完成任务可恢复（持久化 Checkpointer）
- [ ] 新增一条文档级规则触发重审，trace 中只有该分支被重跑
- [ ] 任一节点失败不影响整体流程，且 trace 中有明确记录
- [ ] 可通过 `task_id` 完整回放每个节点的输入输出与耗时

---

## 8. 常见坑

| 坑 | 表现 | 解法 |
| --- | --- | --- |
| Checkpointer 用内存 | 重启后任务消失 | 用 SQLite/PG 持久化 |
| `interrupt` 放在不可序列化的地方 | 崩溃 | 传入/传出的数据必须是 JSON 可序列化 |
| 并行节点同时写同一字段 | 结果丢失 | 状态更新用 reducer（如 `add`）而非覆盖 |
| 规则越来越多导致串行超时 | 用户等待久 | Map-Reduce 并行 + 批处理 + 缓存 |
| 预算只看 token 不看时间 | 仍然卡死 | token、时间、调用次数三重上限 |

---

## 9. 学习对应

对应学习路线 **阶段 5（Agent 编排）**。动手路径：
① 先用纯 Python 写死一条 5 步流程；
② 再改成 LangGraph 状态图（体会状态共享的好处）；
③ 最后加入 `interrupt` 与 Checkpointer（体会"人在环"为什么必须有状态机）。**三步走完你就真正理解了 Agent 与普通链式调用的分界线。**
