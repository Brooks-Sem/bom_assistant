import logging
import uuid
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from excel_writer import write_admin_template
from file_reader import detect_file_type
from llm_client import analyze_bom_with_llm, parse_edit_instruction, parse_lookup_query
from models import AdminTemplateRow, AnalyzeBomResult
from store import ArtifactStore, TaskStore

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s: %(message)s")
log = logging.getLogger(__name__)

mcp = FastMCP("bom-assistant")
_tasks = TaskStore()
_artifacts = ArtifactStore()
_last_task_id: str | None = None


def _remember(task_id: str) -> None:
    global _last_task_id
    _last_task_id = task_id


def _resolve_task_id(task_id: str | None) -> str:
    if task_id and task_id.strip():
        return task_id.strip()
    if _last_task_id:
        return _last_task_id
    for status in ("success", "partial"):
        recent = _tasks.search({"task_type": "analysis", "status": status, "limit": 1})
        if recent:
            return recent[0].task_id
    raise ValueError("找不到可用的历史BOM任务")


def _persist_outputs(task_id: str, rows: list[dict], summary: str, excel_path: str | None, version: int) -> None:
    _artifacts.save(
        task_id=task_id,
        artifact_type="normalized_bom",
        version=version,
        file_name=f"bom_v{version}.json",
        content_type="application/json",
        content={"summary": summary, "rows": rows},
    )
    if excel_path and Path(excel_path).exists():
        _artifacts.save(
            task_id=task_id,
            artifact_type="excel",
            version=version,
            file_name=Path(excel_path).name,
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            source_path=excel_path,
        )


# --- 工具1：BOM 转 Excel ---

@mcp.tool()
def bom_to_excel(file_paths: str, output_name: str = "", user_instruction: str = "") -> dict:
    """将一个或多个采购订单/BOM文件转换为标准化的admin_template Excel。

    支持 xlsx、csv、pdf、图片格式。多个文件用逗号分隔，结果合并到同一个Excel。

    Args:
        file_paths: 输入文件路径，多个文件用逗号分隔
        output_name: 可选的输出文件名前缀（如"烽禾升_3月订单"）
        user_instruction: 可选的附加处理要求
    """
    paths = [p.strip() for p in file_paths.split(",") if p.strip()]
    if not paths:
        raise ValueError("file_paths 不能为空")

    log.info("收到BOM分析请求: %d 个文件", len(paths))

    all_rows: list[dict] = []
    all_errors: list[dict] = []
    all_confirmations: list[dict] = []
    all_warnings: list[dict] = []
    summaries: list[str] = []
    customer_names: list[str] = []
    source_label = output_name.strip() or Path(paths[0]).stem

    for i, fp in enumerate(paths, 1):
        log.info("分析文件 [%d/%d]: %s", i, len(paths), fp)
        try:
            detect_file_type(fp)
            llm_result = analyze_bom_with_llm(fp, user_instruction)
        except ValueError as e:
            all_errors.append({"code": "UNSUPPORTED_FORMAT", "message": f"{fp}: {e}"})
            continue

        rows = []
        for r in llm_result.get("rows", []):
            try:
                rows.append(AdminTemplateRow.model_validate(r).model_dump())
            except Exception:
                all_warnings.append({"row": None, "message": f"跳过无效行数据: {str(r)[:100]}"})
        all_rows.extend(rows)
        all_errors.extend(llm_result.get("errors", []))
        all_confirmations.extend(llm_result.get("needs_confirmation", []))
        all_warnings.extend(llm_result.get("warnings", []))
        if llm_result.get("summary"):
            summaries.append(llm_result["summary"])
        cn = str(llm_result.get("customer_name", "")).strip()
        if cn:
            customer_names.append(cn)

    unique_names = sorted(set(customer_names))
    if len(unique_names) == 1 and len(customer_names) == len(paths):
        company_name = unique_names[0]
    else:
        company_name = source_label
        if len(unique_names) > 1:
            all_warnings.append({"row": None, "message": f"检测到多个客户名称: {', '.join(unique_names)}；已回退使用 {source_label}"})
        elif len(paths) > 1 and unique_names:
            all_warnings.append({"row": None, "message": f"仅部分文件提取到客户名称；已回退使用 {source_label}"})

    excel_path = write_admin_template(all_rows, source_file=source_label) if all_rows else None

    if not all_rows:
        status = "failed"
    elif all_errors or all_confirmations:
        status = "partial"
    else:
        status = "success"

    summary = f"共处理{len(paths)}个文件，提取{len(all_rows)}行。" + " ".join(summaries)
    result_id = str(uuid.uuid4())

    task = _tasks.create(
        task_type="analysis",
        status=status,
        company_name=company_name,
        source_label=source_label,
        user_instruction=user_instruction,
        summary=summary,
        row_count=len(all_rows),
        metadata={"source_files": paths, "result_id": result_id, "customer_names": unique_names},
    )
    _persist_outputs(task.task_id, all_rows, summary, excel_path, version=1) if all_rows else None
    _remember(task.task_id)
    log.info("任务完成: task_id=%s, %d行, Excel=%s", task.task_id, len(all_rows), excel_path)

    return AnalyzeBomResult(
        result_id=result_id,
        task_id=task.task_id,
        status=status,
        summary=summary,
        rows=all_rows,
        errors=all_errors,
        needs_confirmation=all_confirmations,
        warnings=all_warnings,
        excel_output_path=excel_path,
    ).model_dump()


# --- 工具2：BOM 编辑 ---

@mcp.tool()
def bom_edit(edit_instruction: str, task_id: str = "") -> dict:
    """修改已有的BOM数据并重新生成Excel。

    通过自然语言描述修改内容，系统自动定位行和字段进行修改。

    Args:
        edit_instruction: 修改指令（如"第3行数量改成200"、"把怡合达的坦克链数量改为50"）
        task_id: 可选，指定要修改的任务ID。不提供则使用最近一次任务
    """
    base_id = _resolve_task_id(task_id or None)
    base_task = _tasks.get(base_id)
    if not base_task:
        raise ValueError(f"任务不存在: {base_id}")

    bom_data = _artifacts.get_latest_bom(base_id)
    if not bom_data:
        raise ValueError(f"未找到BOM数据: {base_id}")

    try:
        bom_artifact, bom_payload = bom_data
    except (OSError, ValueError) as e:
        raise ValueError(f"BOM数据读取失败: {e}") from e
    base_rows = [AdminTemplateRow.model_validate(r).model_dump() for r in bom_payload.get("rows", [])]

    ops = parse_edit_instruction(edit_instruction, base_rows)
    if not ops:
        raise ValueError("无法从指令中解析出有效的编辑操作，请更明确地描述修改内容")

    updated_rows = [dict(r) for r in base_rows]
    allowed = set(AdminTemplateRow.model_fields.keys())
    applied: list[dict] = []
    errors: list[dict] = []

    for op in ops:
        idx = op.row_index - 1
        if idx < 0 or idx >= len(updated_rows):
            errors.append({"row": op.row_index, "field": op.field, "code": "ROW_OUT_OF_RANGE", "message": f"行{op.row_index}超出范围"})
            continue
        if op.field not in allowed:
            errors.append({"row": op.row_index, "field": op.field, "code": "INVALID_FIELD", "message": f"无效字段: {op.field}"})
            continue
        updated_rows[idx][op.field] = "" if op.new_value is None else str(op.new_value)
        applied.append(op.model_dump())

    if not applied:
        raise ValueError("所有编辑操作均无法执行")

    next_ver = bom_artifact.version + 1
    label = base_task.source_label or base_task.company_name or base_id[:8]
    excel_path = write_admin_template(updated_rows, source_file=f"{label}_v{next_ver}")
    status = "partial" if errors else "success"
    summary = f"对任务{base_id[:8]}应用了{len(applied)}处修改，生成版本{next_ver}。"
    result_id = str(uuid.uuid4())

    new_task = _tasks.create(
        task_type="edit",
        status=status,
        parent_task_id=base_id,
        company_name=base_task.company_name,
        source_label=base_task.source_label,
        user_instruction=edit_instruction,
        summary=summary,
        row_count=len(updated_rows),
        metadata={"result_id": result_id, "base_task_id": base_id, "edits": applied},
    )
    _persist_outputs(new_task.task_id, updated_rows, summary, excel_path, version=next_ver)
    _remember(new_task.task_id)
    log.info("编辑完成: task_id=%s, %d处修改, Excel=%s", new_task.task_id, len(applied), excel_path)

    return AnalyzeBomResult(
        result_id=result_id,
        task_id=new_task.task_id,
        parent_task_id=base_id,
        status=status,
        summary=summary,
        rows=updated_rows,
        errors=errors,
        warnings=[],
        excel_output_path=excel_path,
    ).model_dump()


# --- 工具3：BOM 查询 ---

@mcp.tool()
def bom_lookup(query: str) -> dict:
    """查询历史BOM处理记录。

    支持按客户名称、时间范围、关键词等自然语言查询。

    Args:
        query: 查询描述（如"昨天蚂蚁工场的订单"、"最近处理的BOM"）
    """
    filters = parse_lookup_query(query)
    tasks = _tasks.search(filters.model_dump(exclude_none=True))

    if len(tasks) == 1:
        _remember(tasks[0].task_id)

    return {
        "query": query,
        "filters": filters.model_dump(),
        "count": len(tasks),
        "tasks": [
            {
                "task_id": t.task_id,
                "task_type": t.task_type,
                "status": t.status,
                "company_name": t.company_name,
                "summary": t.summary,
                "row_count": t.row_count,
                "created_at": t.created_at,
            }
            for t in tasks
        ],
    }


if __name__ == "__main__":
    mcp.run(transport="stdio")
