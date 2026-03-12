import json
import logging
import os
from datetime import date

import anthropic
from dotenv import load_dotenv

from file_reader import (
    detect_file_type,
    get_image_media_type,
    get_pdf_media_type,
    read_csv_as_text,
    read_file_as_base64,
    read_xlsx_as_text,
)
from models import AdminTemplateRow, BomEditOperation, BomLookupFilters
from skill_prompt import (
    EDIT_PARSE_PROMPT,
    LOOKUP_PARSE_PROMPT,
    SYSTEM_PROMPT,
    build_user_prompt,
)

load_dotenv()
log = logging.getLogger(__name__)

MODEL_NAME = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-20250514")
BASE_URL = os.getenv("ANTHROPIC_BASE_URL", "https://api.anthropic.com")

_GENERIC_LOOKUP_KEYWORDS = {
    s.casefold()
    for s in ("订单", "采购订单", "采购", "bom", "文件", "文档", "表格", "记录", "历史", "数据", "任务")
}


def _client() -> anthropic.Anthropic:
    return anthropic.Anthropic(
        base_url=BASE_URL,
        default_headers={"User-Agent": "claude-code/1.0"},
    )


def _strip_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        nl = text.find("\n")
        if nl != -1:
            text = text[nl + 1:]
    if text.endswith("```"):
        text = text[:-3]
    return text.strip()


def _request_json(system: str, user_text: str, max_tokens: int = 2048) -> dict:
    resp = _client().messages.create(
        model=MODEL_NAME,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": user_text}],
    )
    return json.loads(_strip_fences(resp.content[0].text))


# --- BOM 分析 ---

def _build_messages(file_path: str, user_instruction: str) -> list[dict]:
    file_type = detect_file_type(file_path)

    if file_type in ("xlsx", "csv"):
        text = read_xlsx_as_text(file_path) if file_type == "xlsx" else read_csv_as_text(file_path)
        return [{"role": "user", "content": build_user_prompt(text, user_instruction)}]

    if file_type == "pdf":
        b64 = read_file_as_base64(file_path)
        return [
            {
                "role": "user",
                "content": [
                    {"type": "document", "source": {"type": "base64", "media_type": get_pdf_media_type(), "data": b64}},
                    {"type": "text", "text": build_user_prompt("（见上方PDF文档）", user_instruction)},
                ],
            }
        ]

    if file_type == "image":
        b64 = read_file_as_base64(file_path)
        return [
            {
                "role": "user",
                "content": [
                    {"type": "image", "source": {"type": "base64", "media_type": get_image_media_type(file_path), "data": b64}},
                    {"type": "text", "text": build_user_prompt("（见上方图片）", user_instruction)},
                ],
            }
        ]

    raise ValueError(f"不支持的文件类型: {file_type}")


def analyze_bom_with_llm(file_path: str, user_instruction: str = "") -> dict:
    messages = _build_messages(file_path, user_instruction)
    log.info("调用 Claude API, model=%s, file=%s", MODEL_NAME, file_path)

    resp = _client().messages.create(
        model=MODEL_NAME,
        max_tokens=8192,
        system=SYSTEM_PROMPT,
        messages=messages,
    )

    try:
        return json.loads(_strip_fences(resp.content[0].text))
    except json.JSONDecodeError as e:
        log.error("LLM JSON 解析失败: %s", e)
        return {
            "summary": "模型输出格式异常，无法解析",
            "rows": [],
            "errors": [{"code": "LLM_PARSE_ERROR", "message": str(e)}],
            "needs_confirmation": [],
            "warnings": [],
        }


# --- 编辑指令解析 ---

def parse_edit_instruction(instruction: str, rows: list[dict]) -> list[BomEditOperation]:
    indexed = [{"row_index": i + 1, **r} for i, r in enumerate(rows)]
    payload = {
        "edit_instruction": instruction,
        "available_fields": list(AdminTemplateRow.model_fields.keys()),
        "rows": indexed,
    }
    try:
        result = _request_json(EDIT_PARSE_PROMPT, json.dumps(payload, ensure_ascii=False))
    except (json.JSONDecodeError, anthropic.APIError) as e:
        log.error("编辑指令解析失败: %s", e)
        return []

    ops = []
    for item in result.get("edits", []):
        try:
            ops.append(BomEditOperation.model_validate(item))
        except Exception:
            log.warning("跳过无效编辑操作: %s", item)
    return ops


# --- 查询解析 ---

def parse_lookup_query(query: str) -> BomLookupFilters:
    payload = {"query": query, "current_date": date.today().isoformat()}
    try:
        result = _request_json(LOOKUP_PARSE_PROMPT, json.dumps(payload, ensure_ascii=False), max_tokens=1024)
    except (json.JSONDecodeError, anthropic.APIError) as e:
        log.error("查询解析失败: %s", e)
        return BomLookupFilters(keywords=[query])

    company_name = str(result.get("company_name", "")).strip() or None
    raw_keywords = result.get("keywords", [])
    if not isinstance(raw_keywords, list):
        raw_keywords = [] if raw_keywords in (None, "") else [raw_keywords]
    keywords = [
        kw for kw in (str(k).strip() for k in raw_keywords)
        if kw and kw.casefold() not in _GENERIC_LOOKUP_KEYWORDS and kw != (company_name or "")
    ]

    normalized = {
        "company_name": company_name,
        "task_type": (str(result.get("task_type", "")).strip() or None),
        "status": (str(result.get("status", "")).strip() or None),
        "date_from": (str(result.get("date_from", "")).strip() or None),
        "date_to": (str(result.get("date_to", "")).strip() or None),
        "keywords": keywords,
        "limit": result.get("limit", 10),
    }
    try:
        return BomLookupFilters.model_validate(normalized)
    except Exception:
        return BomLookupFilters(keywords=[query])
