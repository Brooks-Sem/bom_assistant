---
name: bom-assistant
description: BOM/采购订单助手 — 识别并转换新文件、查询历史任务、修改已生成BOM；适用于"转换/解析/提取/查询/更正/编辑/回查"等请求。
version: 2.1.0
metadata:
  openclaw:
    emoji: "📊"
    requires:
      env:
        - ANTHROPIC_API_KEY
        - ANTHROPIC_BASE_URL
        - ANTHROPIC_MODEL
      bins:
        - python3
    primaryEnv: ANTHROPIC_API_KEY
    install:
      - id: script
        kind: command
        command: bash {baseDir}/install.sh
        label: "运行安装脚本"
---

# BOM 助手

提供三个工具：`bom_to_excel`（转换）、`bom_edit`（编辑）、`bom_lookup`（查询）。

## bom_to_excel — BOM 转 Excel

当用户提到以下触发词或场景时使用：
- 转换、导入、解析、识别、提取、生成Excel、处理这个文件/附件
- 提供了 xlsx、csv、pdf 或图片格式的新采购订单/BOM 文件
- 需要把原始订单整理成标准化 admin_template

不要在以下场景使用：
- 只是查询历史记录、最近任务、某客户之前的订单
- 只是修改已经生成的 BOM 某几行或某个字段

参数：
- `file_paths`（必填）：文件绝对路径，多个用逗号分隔
- `output_name`（可选）：输出文件名前缀
- `user_instruction`（可选）：附加处理要求

## bom_edit — 修改已有 BOM

当用户提到以下触发词或场景时使用：
- 修改、更正、调整、替换、补充、删除、把第N行改成……
- 要求修改已生成的 BOM 数据（如"第3行数量改成200"）
- 要求调整某个产品、型号或字段的信息

不要在以下场景使用：
- 用户提供的是一个全新的原始文件，还没有先做解析转换
- 只是想查看历史记录、最近任务或某客户订单

参数：
- `edit_instruction`（必填）：自然语言修改指令
- `task_id`（可选）：指定任务ID，不提供则使用最近一次

## bom_lookup — 查询历史记录

当用户提到以下触发词或场景时使用：
- 查询、查找、回查、看看之前、历史、最近、昨天、上周、某客户的订单
- 查询之前处理过的 BOM（如"昨天蚂蚁工场的订单"）
- 查看最近的处理记录或指定时间范围内的任务

不要在以下场景使用：
- 用户要求解析一个新文件并生成 Excel
- 用户要求直接修改某一行、某个字段或某个产品的数据

参数：
- `query`（必填）：自然语言查询

## 工具组合

如果用户既要"先找再改"，先用 `bom_lookup` 定位任务，再用 `bom_edit`。
如果用户提供了新文件又要求"导出为标准表"，先用 `bom_to_excel`，必要时再 `bom_edit`。

## 结果处理

所有工具返回 JSON 包含 `status`（success/partial/failed）、`summary`、`task_id`。

1. `success` → 告知用户结果，给出 Excel 路径
2. `partial` → 告知用户结果已生成但有问题，列出 `errors` 和 `needs_confirmation`
3. `failed` → 告知用户失败原因
