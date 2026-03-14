import json
import logging
import os
import re
import time
from datetime import date

import anthropic
import httpx
from dotenv import load_dotenv

from file_reader import (
    detect_file_type,
    get_image_media_type,
    get_pdf_media_type,
    read_csv_as_text,
    read_file_as_base64,
    read_pdf_as_text,
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


def _env_int(name: str, default: int) -> int:
    raw = (os.getenv(name) or "").strip()
    try:
        v = int(raw)
        return v if v > 0 else default
    except ValueError:
        return default


ANALYZE_MAX_TOKENS = _env_int("ANTHROPIC_MAX_TOKENS", 32768)

def _env_int_allow_zero(name: str, default: int) -> int:
    raw = (os.getenv(name) or "").strip()
    try:
        v = int(raw)
        return v if v >= 0 else default
    except ValueError:
        return default

_API_MAX_RETRIES = _env_int_allow_zero("ANTHROPIC_MAX_RETRIES", 3)
_API_RETRY_BASE_SECONDS = 5
_API_RETRY_BUDGET_SECONDS = 90
_RETRYABLE_STATUS_CODES = {429, 502, 503, 524}

_GENERIC_LOOKUP_KEYWORDS = {
    s.casefold()
    for s in ("订单", "采购订单", "采购", "bom", "文件", "文档", "表格", "记录", "历史", "数据", "任务")
}


_http_client = httpx.Client(
    timeout=httpx.Timeout(connect=30.0, read=600.0, write=120.0, pool=30.0),
)


def _client() -> anthropic.Anthropic:
    return anthropic.Anthropic(
        base_url=BASE_URL,
        default_headers={"User-Agent": "claude-code/1.0"},
        http_client=_http_client,
    )


def _strip_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        nl = text.find("\n")
        text = text[nl + 1:] if nl != -1 else text[3:]
    if text.endswith("```"):
        text = text[:-3]
    return text.strip()


def _extract_response_text(resp) -> str:
    for block in resp.content or []:
        if hasattr(block, "text") and block.text:
            return block.text
    return ""


def _extract_string_field(text: str, key: str, default: str = "") -> str:
    m = re.search(rf'"{re.escape(key)}"\s*:\s*("(?:\\.|[^"\\])*")', text, re.DOTALL)
    if not m:
        return default
    try:
        return json.loads(m.group(1))
    except json.JSONDecodeError:
        return default


def _repair_truncated_json(raw_text: str) -> dict | None:
    text = _strip_fences(raw_text)
    rows_pos = text.find('"rows"')
    if rows_pos == -1:
        return None
    array_start = text.find("[", rows_pos)
    if array_start == -1:
        return None

    decoder = json.JSONDecoder()
    idx = array_start + 1
    rows: list[dict] = []
    while idx < len(text):
        while idx < len(text) and text[idx] in " \r\n\t,":
            idx += 1
        if idx >= len(text) or text[idx] == "]":
            break
        try:
            obj, end = decoder.raw_decode(text, idx)
        except json.JSONDecodeError:
            break
        if isinstance(obj, dict):
            rows.append(obj)
        idx = end

    if not rows:
        return None
    msg = "模型输出因 max_tokens 被截断，已恢复部分完整行数据"
    return {
        "summary": _extract_string_field(text, "summary", msg),
        "customer_name": _extract_string_field(text, "customer_name"),
        "rows": rows,
        "errors": [{"code": "LLM_OUTPUT_TRUNCATED", "message": msg}],
        "needs_confirmation": [],
        "warnings": [{"row": None, "message": msg}],
    }


def _request_json(system: str, user_text: str, max_tokens: int = 2048) -> dict:
    resp = _client().messages.create(
        model=MODEL_NAME,
        max_tokens=max_tokens,
        system=[{"type": "text", "text": system}],
        messages=[{"role": "user", "content": user_text}],
    )
    return json.loads(_strip_fences(_extract_response_text(resp)))


# --- BOM 分析 ---

def _build_messages(file_path: str, user_instruction: str) -> list[dict]:
    file_type = detect_file_type(file_path)

    if file_type in ("xlsx", "csv"):
        text = read_xlsx_as_text(file_path) if file_type == "xlsx" else read_csv_as_text(file_path)
        return [{"role": "user", "content": build_user_prompt(text, user_instruction)}]

    if file_type == "pdf":
        pdf_text = read_pdf_as_text(file_path)
        if pdf_text:
            log.info("PDF 文本提取成功，走文本路径: file=%s, chars=%d", file_path, len(pdf_text))
            return [{"role": "user", "content": build_user_prompt(pdf_text, user_instruction)}]
        log.info("PDF 文本提取无结果，降级为 base64 上传: file=%s", file_path)
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
    log.info("调用 Claude API (streaming), model=%s, max_tokens=%d, file=%s", MODEL_NAME, ANALYZE_MAX_TOKENS, file_path)

    last_error: Exception | None = None
    resp = None
    stream_text = ""
    t0 = time.monotonic()
    for attempt in range(_API_MAX_RETRIES + 1):
        try:
            with _client().messages.stream(
                model=MODEL_NAME,
                max_tokens=ANALYZE_MAX_TOKENS,
                system=[{"type": "text", "text": SYSTEM_PROMPT}],
                messages=messages,
            ) as stream:
                stream_text = stream.get_final_text()
                resp = stream.get_final_message()
            break
        except (anthropic.APITimeoutError, anthropic.APIConnectionError, httpx.TimeoutException) as e:
            last_error = e
            wait = _API_RETRY_BASE_SECONDS * (2 ** attempt)
        except anthropic.APIStatusError as e:
            code = getattr(e, "status_code", None) or getattr(
                getattr(e, "response", None), "status_code", None
            )
            if code not in _RETRYABLE_STATUS_CODES:
                raise
            last_error = e
            wait = _API_RETRY_BASE_SECONDS * (2 ** attempt)
            if code == 429:
                hdrs = getattr(getattr(e, "response", None), "headers", None)
                ra = hdrs.get("Retry-After") if hdrs else None
                if ra:
                    try:
                        wait = max(wait, float(ra))
                    except (TypeError, ValueError):
                        pass

        elapsed = time.monotonic() - t0
        budget_left = _API_RETRY_BUDGET_SECONDS - elapsed
        if attempt < _API_MAX_RETRIES and budget_left > wait:
            log.warning(
                "Claude API 调用失败，准备重试: attempt=%d/%d, wait=%.0fs, elapsed=%.0fs, file=%s, error=%s",
                attempt + 1, _API_MAX_RETRIES, wait, elapsed, file_path, last_error,
            )
            time.sleep(wait)
            continue

        err_type = type(last_error).__name__ if last_error else "Unknown"
        log.error("Claude API 调用失败: file=%s, attempts=%d, elapsed=%.0fs, error=%s", file_path, attempt + 1, elapsed, last_error)
        return {
            "summary": f"模型分析失败（{err_type}），已重试 {attempt} 次",
            "customer_name": "",
            "rows": [],
            "errors": [{"code": "LLM_API_ERROR", "message": f"API 请求失败（已重试 {attempt} 次）: {last_error}"}],
            "needs_confirmation": [],
            "warnings": [{"row": None, "message": "请稍后重试，或联系管理员检查 API 配置"}],
        }
    raw_text = stream_text or _extract_response_text(resp)
    if not raw_text:
        block_types = [type(b).__name__ for b in (resp.content or [])]
        log.error(
            "LLM 返回空内容: stop_reason=%s, blocks=%s, model=%s, file=%s",
            getattr(resp, "stop_reason", None), block_types,
            getattr(resp, "model", None), file_path,
        )
        return {
            "summary": "模型返回空内容",
            "customer_name": "",
            "rows": [],
            "errors": [{"code": "LLM_EMPTY_RESPONSE", "message": f"stop_reason={getattr(resp, 'stop_reason', None)}, blocks={block_types}"}],
            "needs_confirmation": [],
            "warnings": [],
        }

    try:
        return json.loads(_strip_fences(raw_text))
    except json.JSONDecodeError as e:
        if getattr(resp, "stop_reason", None) == "max_tokens":
            repaired = _repair_truncated_json(raw_text)
            if repaired is not None:
                log.warning("LLM 输出被截断，已恢复 %d 行: file=%s", len(repaired["rows"]), file_path)
                return repaired
            log.error("LLM 输出被截断且无法修复: %s", e)
            return {
                "summary": "模型输出被截断，且无法解析完整 JSON",
                "customer_name": "",
                "rows": [],
                "errors": [{"code": "LLM_OUTPUT_TRUNCATED", "message": str(e)}],
                "needs_confirmation": [],
                "warnings": [{"row": None, "message": "请缩小输入范围或提高 ANTHROPIC_MAX_TOKENS"}],
            }
        log.error("LLM JSON 解析失败: %s", e)
        return {
            "summary": "模型输出格式异常，无法解析",
            "customer_name": "",
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
