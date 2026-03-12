import base64
from pathlib import Path

from openpyxl import load_workbook


SUPPORTED_EXTENSIONS = {".xlsx", ".csv", ".pdf", ".png", ".jpg", ".jpeg"}


def detect_file_type(file_path: str) -> str:
    ext = Path(file_path).suffix.lower()
    if ext == ".xlsx":
        return "xlsx"
    if ext == ".csv":
        return "csv"
    if ext == ".pdf":
        return "pdf"
    if ext in {".png", ".jpg", ".jpeg"}:
        return "image"
    raise ValueError(f"不支持的文件格式: {ext}")


def read_xlsx_as_text(file_path: str) -> str:
    wb = load_workbook(file_path, read_only=True, data_only=True)
    parts: list[str] = []
    for sheet_name in wb.sheetnames:
        ws = wb[sheet_name]
        rows = list(ws.iter_rows(values_only=True))
        if not rows:
            continue
        parts.append(f"[Sheet: {sheet_name}]")
        headers = [str(c) if c is not None else "" for c in rows[0]]
        parts.append("\t".join(headers))
        for row in rows[1:]:
            cells = [str(c) if c is not None else "" for c in row]
            parts.append("\t".join(cells))
    wb.close()
    return "\n".join(parts)


def read_csv_as_text(file_path: str) -> str:
    return Path(file_path).read_text(encoding="utf-8")


def read_file_as_base64(file_path: str) -> str:
    data = Path(file_path).read_bytes()
    return base64.standard_b64encode(data).decode("ascii")


def get_pdf_media_type() -> str:
    return "application/pdf"


def get_image_media_type(file_path: str) -> str:
    ext = Path(file_path).suffix.lower()
    mapping = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg"}
    return mapping.get(ext, "application/octet-stream")
