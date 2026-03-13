---
name: bom-assistant
description: BOM/采购订单助手 — 识别并转换新文件、查询历史任务、修改已生成BOM；适用于"转换/解析/提取/查询/更正/编辑/回查"等请求。
version: 2.5.0
metadata:
  openclaw:
    emoji: "📊"
    requires:
      bins:
        - python3
    install:
      - id: script
        kind: command
        command: bash {baseDir}/install.sh
        label: "运行安装脚本"
---

# BOM 助手

将采购订单/BOM文件转换为标准化Excel、修改已生成的BOM、查询历史处理记录。

## 输出配置

- **输出目录**: `$HOME/.openclaw/workspace/media/outbound/bom-assistant`
- **目录结构**: `{输出目录}/{YYYY-MM}/{客户名}/admin_template_{来源}_{时间戳}.xlsx`
- **所有命令**必须通过 `--outdir` 指定输出目录，确保文件可被 gateway 正确发送

## Quick Reference

- **转换BOM**: `cd {baseDir} && .venv/bin/python cli.py to-excel "<file_path>" --outdir "$HOME/.openclaw/workspace/media/outbound/bom-assistant"`
- **编辑BOM**: `cd {baseDir} && .venv/bin/python cli.py edit "<instruction>" --outdir "$HOME/.openclaw/workspace/media/outbound/bom-assistant"`
- **查询历史**: `cd {baseDir} && .venv/bin/python cli.py lookup "<query>"`

## to-excel — BOM 转 Excel

当用户提供了新的采购订单/BOM文件（xlsx、csv、pdf、图片），需要转换、解析、识别、提取、生成Excel时使用。

**单个文件**:
```bash
cd {baseDir} && .venv/bin/python cli.py to-excel "/path/to/file.xlsx" --outdir "$HOME/.openclaw/workspace/media/outbound/bom-assistant"
```

**多个文件**（逗号分隔，合并到同一个Excel）:
```bash
cd {baseDir} && .venv/bin/python cli.py to-excel "/path/a.xlsx,/path/b.pdf" --outdir "$HOME/.openclaw/workspace/media/outbound/bom-assistant"
```

**指定输出名前缀**:
```bash
cd {baseDir} && .venv/bin/python cli.py to-excel "/path/to/file.xlsx" "客户名_3月订单" --outdir "$HOME/.openclaw/workspace/media/outbound/bom-assistant"
```

**附加处理要求**:
```bash
cd {baseDir} && .venv/bin/python cli.py to-excel "/path/to/file.xlsx" "" "只提取前10行" --outdir "$HOME/.openclaw/workspace/media/outbound/bom-assistant"
```

不要在以下场景使用：
- 只是查询历史记录、最近任务
- 只是修改已经生成的BOM某几行

## edit — 修改已有 BOM

当用户要修改、更正、调整、替换已生成的BOM数据时使用（如"第3行数量改成200"、"把品牌改成怡合达"）。

**修改最近一次任务**:
```bash
cd {baseDir} && .venv/bin/python cli.py edit "第3行数量改成200" --outdir "$HOME/.openclaw/workspace/media/outbound/bom-assistant"
```

**指定任务ID**（从lookup结果获取）:
```bash
cd {baseDir} && .venv/bin/python cli.py edit "数量改成50" "task-id-here" --outdir "$HOME/.openclaw/workspace/media/outbound/bom-assistant"
```

不提供task_id时自动使用最近一次处理的任务。

不要在以下场景使用：
- 用户提供了全新的原始文件，还没有解析转换
- 只是想查看历史记录

## lookup — 查询历史记录

当用户查询、回查、查看之前处理过的BOM记录时使用。

```bash
cd {baseDir} && .venv/bin/python cli.py lookup "昨天蚂蚁工场的订单"
```

```bash
cd {baseDir} && .venv/bin/python cli.py lookup "最近处理的BOM"
```

不要在以下场景使用：
- 用户要求解析新文件
- 用户要求修改已有BOM的数据

## Workflow

- **先查再改**: 先 `lookup` 定位任务ID → 再 `edit` 修改
- **新文件处理**: 先 `to-excel` 转换 → 需要时再 `edit` 修改

## Result Handling

所有命令输出 JSON，包含 `status`（success/partial/failed）、`summary`、`task_id`。

1. `success` → 告知用户结果和 `excel_output_path` 路径
2. `partial` → 已生成但有问题，查看 `errors` 和 `needs_confirmation`
3. `failed` → 告知用户 `error` 中的失败原因

## 回复规范（必须严格遵守）

### 执行前
在运行命令之前，先用一句话告诉用户你要做什么，例如：
- "正在解析您的采购订单文件，请稍候..."
- "正在查询蚂蚁工场的历史订单..."
- "正在修改第3行的数量..."

### 执行后
命令完成后，必须在**同一条回复中**完整汇报结果，不要拆成多条消息。根据 status 字段组织回复：

**success 示例**:
> 已完成！共提取了 25 行物料数据。
> - 客户：蚂蚁工场
> - 文件：/path/to/output.xlsx
> - 任务ID：abc12345

**partial 示例**:
> 已生成 Excel（20行），但有以下问题需要确认：
> - 第5行：数量字段为空，请补充
> - 第12行：品牌未识别
> 文件：/path/to/output.xlsx

**failed 示例**:
> 处理失败：不支持的文件格式（.doc）。请提供 xlsx、csv、pdf 或图片格式的文件。

### 关键规则
1. **不要等用户追问** — 命令执行完必须立即主动汇报完整结果
2. **一次说完** — 把状态、摘要、文件路径、错误全部放在一条回复中
3. **失败必报** — 出错时必须立即告知用户原因和建议的下一步操作
4. **不要重复跑命令** — 如果命令已经返回结果（无论成功或失败），直接汇报，不要再跑一次
