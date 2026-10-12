# M8 · API 服务与持久化（Service & Storage）

> **职责**：把 M1~M7 的能力包装为稳定的对外服务，并负责所有数据的存取与一致性。
> **对应需求**：R-04（持久化数据管理）、NFR-05（可回放）
> **关键词**：FastAPI 分层、异步任务、事务边界、缓存键、迁移策略

---

## 1. 服务分层

```
api/          路由层：只做参数校验、鉴权、调用 service、组装响应
  ↓
service/      业务层：编排事务边界、调用 agent 与各领域服务（不含 HTTP 概念）
  ↓
domain/       领域层：documents / rules / audit / review 各自的领域逻辑
  ↓
infra/        基础设施：db / vectorstore / storage / llm_client / mineru_client / cache
```

**铁律**：`domain` 层不允许 import `fastapi`；`infra` 层不允许知道业务语义。这样即使将来换 Web 框架也不需要重写核心逻辑。

---

## 2. 任务执行模型

| 阶段 | 方案 | 理由 |
| --- | --- | --- |
| 起步 | `FastAPI BackgroundTasks` | 零额外组件，单机够用 |
| 进阶 | `asyncio.Semaphore` 限并发 + 进程内队列 | 防止同时解析 50 个文件把机器打爆 |
| 生产 | Celery + Redis（或 RQ） | 支持重试、延时、多 worker、水平扩展 |

```python
sem = asyncio.Semaphore(settings.MAX_CONCURRENT_TASKS)

async def submit_audit(task_id: str):
    async with sem:
        await graph.ainvoke(state, config={"configurable": {"thread_id": task_id}})
```

**进度上报**：每个节点进入/退出时向 `WS /ws/tasks/{id}` 推消息，前端画进度条；同时写库，页面刷新也能恢复进度。

---

## 3. 存储设计

| 数据 | 存储位置 | 说明 |
| --- | --- | --- |
| 原始文件 | `data/docs/{hash}.{ext}`（本地）或对象存储 | 文件名用 hash，天然去重 |
| 解析产物 blocks/chunks | 数据库 + `data/parsed/{version_id}.json.gz` 冷备 | 量大，JSON 压缩存一份便于整体重放 |
| 向量 | Chroma `data/index/chroma`（起步）→ pgvector | 通过 `VectorStore` 抽象接口隔离 |
| BM25 | 内存构建 + `data/index/bm25.pkl` | 文档规模不大时无需 ES |
| 报告 | `data/reports/{task_id}.md/.docx/.pdf` | 生成后复用下载 |
| Trace | 数据库 `t_trace_step` | 定期归档，保留 90 天热数据 |

### 3.1 三层缓存键（省钱的核心）

```
解析缓存:   key = file_hash + parse_mode
索引缓存:   key = version_id + chunk_params_version
LLM 缓存:   key = version_id + rule_version + prompt_version + evidence_digest
```

其中 `evidence_digest` 取候选 chunk id 集合的哈希。**这样"只改一条规则"时只有该规则的判定会真正花钱。**

---

## 4. 事务一致性

| 场景 | 策略 |
| --- | --- |
| 解析成功但索引失败 | 版本记录标记 `index_failed`，允许重试；不影响已落库 blocks |
| 审核中途失败 | 已产出的 findings 保留（可能有价值），任务标记 `failed` 并记录 trace |
| 删除文档 | 级联删除 versions/blocks/chunks/tasks/findings，异步清理文件与向量 |
| 规则修改 | 不允许原地改：`version+1` 并新建记录，旧任务仍指向旧版本 → 历史结果可复现 |

> **绝不物理删除 finding 或 version**。想想审计场景：三个月后有人问"当初为什么没报这条"，你必须能答。

---

## 5. 安全与权限（最小实现也要有）

- 所有接口经 `tenant_id` 过滤，**在 SQL 层强制过滤**，不只靠前端；
- 文件下载走后端代理，不暴露物理路径；
- 上传校验：类型白名单（不只信 `Content-Type`，用 magic bytes）、大小上限、文件名消毒；
- 密钥只在 `.env`/密钥管理服务，禁止进代码库与日志；日志脱敏（API Key、身份证、手机号）；
- 每个写操作记录 `actor + trace_id`。

---

## 6. 输入 / 输出契约

对外 API 完全以 [03-数据模型与接口契约](../03-数据模型与接口契约.md) 为准，本模块不得私自增加字段或改语义。

---

## 7. 单元验收（DoD）

- [ ] `/docs` 页面与 03 文档的接口清单 100% 对得上
- [ ] 服务重启后未完成任务可恢复进度
- [ ] 同一份文档重复上传不产生第二次解析计费
- [ ] 去掉 `tenant_id` 过滤的 SQL 无法查到其他租户数据（有自动化测试覆盖）
- [ ] 日志中搜不到任何明文密钥或完整身份证号

---

## 8. 常见坑

| 坑 | 表现 | 解法 |
| --- | --- | --- |
| BackgroundTasks 中段出错无人知 | 任务永远卡 running | 统一 try/except + finally 写终态 + 心跳 |
| 大文件同步读取爆内存 | OOM | 流式落盘，不做 `file.read()` 整体入内存 |
| 同步 ORM 调用阻塞事件循环 | 接口变慢 | 用异步驱动或放到线程池 |
| 只cache到最后一层 | 重审仍然贵 | 三层缓存都要有 |
| SQLite 并发写锁 | `database is locked` | 开 WAL + 缩短事务；并发上来就迁 PG |

---

## 9. 学习对应

对应学习路线 **阶段 6**。动手建议：先用 SQLite + BackgroundTasks 把"上传→任务→结果"跑通，再回头补事务、缓存和权限。**先有闭环，再谈工程完备。**
