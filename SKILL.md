---
name: bom-assistant
description: BOM/采购订单助手 — 识别并转换新文件、查询历史任务、修改已生成BOM；适用于"转换/解析/提取/查询/更正/编辑/回查"等请求。
version: 2.2.0
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

## Quick Reference

IMPORTANT: All commands must run from the skill directory. Set it first:

```bash
SKILL_DIR=/mnt/skills/user/bom_assistant
[ -d "$SKILL_DIR" ] || SKILL_DIR="$HOME/.openclaw/skills/bom_assistant"
```

- **转换BOM**: `cd "$SKILL_DIR" && .venv/bin/python cli.py to-excel "<file_path>"`
- **编辑BOM**: `cd "$SKILL_DIR" && .venv/bin/python cli.py edit "<instruction>"`
- **查询历史**: `cd "$SKILL_DIR" && .venv/bin/python cli.py lookup "<query>"`

## to-excel — BOM 转 Excel

当用户提供了新的采购订单/BOM文件（xlsx、csv、pdf、图片），需要转换、解析、识别、提取、生成Excel时使用。

**单个文件**:
```bash
cd "$SKILL_DIR" && .venv/bin/python cli.py to-excel "/path/to/file.xlsx"
```

**多个文件**（逗号分隔，合并到同一个Excel）:
```bash
cd "$SKILL_DIR" && .venv/bin/python cli.py to-excel "/path/a.xlsx,/path/b.pdf"
```

**指定输出名前缀**:
```bash
cd "$SKILL_DIR" && .venv/bin/python cli.py to-excel "/path/to/file.xlsx" "客户名_3月订单"
```

**附加处理要求**:
```bash
cd "$SKILL_DIR" && .venv/bin/python cli.py to-excel "/path/to/file.xlsx" "" "只提取前10行"
```

不要在以下场景使用：
- 只是查询历史记录、最近任务
- 只是修改已经生成的BOM某几行

## edit — 修改已有 BOM

当用户要修改、更正、调整、替换已生成的BOM数据时使用（如"第3行数量改成200"、"把品牌改成怡合达"）。

**修改最近一次任务**:
```bash
cd "$SKILL_DIR" && .venv/bin/python cli.py edit "第3行数量改成200"
```

**指定任务ID**（从lookup结果获取）:
```bash
cd "$SKILL_DIR" && .venv/bin/python cli.py edit "数量改成50" "task-id-here"
```

不提供task_id时自动使用最近一次处理的任务。

不要在以下场景使用：
- 用户提供了全新的原始文件，还没有解析转换
- 只是想查看历史记录

## lookup — 查询历史记录

当用户查询、回查、查看之前处理过的BOM记录时使用。

```bash
cd "$SKILL_DIR" && .venv/bin/python cli.py lookup "昨天蚂蚁工场的订单"
```

```bash
cd "$SKILL_DIR" && .venv/bin/python cli.py lookup "最近处理的BOM"
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
