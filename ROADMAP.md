# BOM Assistant 技术路线

## 系统架构

```
┌─────────────┐
│  企业微信     │  用户入口
└──────┬──────┘
       │ Webhook / 消息推送
┌──────▼──────┐
│  OpenClaw    │  Agent 层：意图识别 → 工具路由 → 结果呈现
│  (Agent)     │  内置企业微信 Channel
└──────┬──────┘
       │ MCP (stdio)
┌──────▼──────────────────────────────────┐
│  bom-assistant (FastMCP)                │
│                                         │
│  ┌─────────────┐ ┌──────────┐ ┌───────┐│
│  │bom_to_excel  │ │bom_edit  │ │bom_   ││
│  │  解析转换    │ │ 编辑修改 │ │lookup ││
│  └──────┬──────┘ └────┬─────┘ └───┬───┘│
│         │             │           │     │
│  ┌──────▼─────────────▼───────────▼───┐ │
│  │       llm_client (Claude API)      │ │
│  │  分析 / 编辑解析 / 查询解析        │ │
│  └────────────────────────────────────┘ │
│  ┌────────────────────────────────────┐ │
│  │       store (SQLite + Blobs)       │ │
│  │  TaskStore / ArtifactStore         │ │
│  └────────────────────────────────────┘ │
└─────────────────────────────────────────┘
       │ (P3: HTTP)
┌──────▼──────┐
│  ERP 系统    │  报价提交 / 状态查询
└─────────────┘
```

## 数据模型

```
tasks
├── task_id (PK)
├── parent_task_id (FK → tasks)    # 编辑链：v1 → v2 → v3
├── task_type: analysis | edit
├── status: success | partial | failed
├── company_name                    # LLM 提取的客户名
├── source_label                    # 文件名/用户指定名
├── summary / row_count
└── created_at / updated_at

artifacts
├── artifact_id (PK)
├── task_id (FK → tasks)
├── artifact_type: source | normalized_bom | excel
├── version
├── storage_key → data/blobs/{task_id}/{artifact_id}.ext
└── file_name / content_type
```

**核心原则**：结构化 BOM JSON 是 truth source，Excel 是派生物，可随时重新生成。

## 阶段规划

### P1 + P2（已完成 ✓）

| 能力 | 实现 |
|------|------|
| BOM 文件解析 | xlsx / csv / pdf / 图片 → 21 列 admin_template |
| 表头鲁棒匹配 | 4 级优先级：精确 → 归一化 → 同义词 → 值模式推断 |
| 客户名提取 | LLM 从文档抬头/版式提取，多文件一致性校验 |
| 持久化 | SQLite WAL + 本地 Blob 存储 |
| 历史查询 | 自然语言 → 结构化 filter，泛化词过滤 |
| BOM 编辑 | 自然语言编辑指令 → 结构化操作，版本链追踪 |
| 多文件合并 | 多个输入文件合并到同一 Excel |

### P3：ERP 对接（待启动）

```
bom-assistant
  ├── quote_submit(task_id) → ERP API → 报价单
  └── quote_status(task_id) → ERP API → 进度查询

新增表：
  quote_jobs (quote_id, task_id, erp_ref, status, submitted_at, responded_at)
```

**前置条件**：ERP API 文档就绪、测试环境可用

**关键决策**：
- 同步提交 vs 异步轮询：取决于 ERP 响应时间
- 报价状态变更是否需要主动通知用户（→ P4）

### P4：通知推送（依赖 P3）

```
notification_outbox (id, task_id, channel, payload, status, retry_count)
```

- 报价完成 / 状态变更时，通过 OpenClaw Channel 推送到企业微信
- 需要 OpenClaw 提供回调或轮询机制
- 考虑重试策略和幂等性

## 已知限制

| 项目 | 现状 | 改进方向 |
|------|------|----------|
| 查询粒度 | 仅搜索任务级元数据 | 行级索引表（按产品名/型号检索） |
| 并发 | RLock + WAL 单进程安全 | 多实例需迁移 PostgreSQL |
| 文件大小 | 受 Claude API max_tokens 限制 | 大文件分片处理 |
| 编辑能力 | 单行字段修改 | 批量删除行、插入行、行排序 |
