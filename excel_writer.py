import os
import re
import shutil
from datetime import datetime
from pathlib import Path

from openpyxl import load_workbook

TEMPLATE_PATH = Path(__file__).parent / "admin_template.xlsx"

_OPENCLAW_OUTBOUND = Path.home() / ".openclaw" / "workspace" / "media" / "outbound" / "bom-assistant"
_FALLBACK_OUTPUT = Path(__file__).resolve().parent / "output"
OUTPUT_ROOT = Path(os.getenv("BOM_OUTPUT_DIR", "")).resolve() if os.getenv("BOM_OUTPUT_DIR") else (
    _OPENCLAW_OUTBOUND if _OPENCLAW_OUTBOUND.parent.exists() else _FALLBACK_OUTPUT
)

FIELD_KEYS = [
    "customer_part_no",
    "customer_product_name",
    "product_model",
    "product_name",
    "brand",
    "quantity",
    "remark_customer",
    "remark_supply_chain",
    "customer_project_no",
    "customer_material_no",
    "inventory_feature",
    "major_category",
    "minor_category",
    "supply_org",
    "attachment_filename",
    "remark_purchase",
    "customer_expected_delivery",
    "customer_expected_price",
    "warehouse_factory",
    "sales_unit_price_tax",
    "shipment_date",
]

_FS_INVALID_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]+')
_MULTI_UNDERSCORE = re.compile(r"_+")


def _sanitize_segment(value: str, fallback: str = "unknown") -> str:
    cleaned = _FS_INVALID_CHARS.sub("_", (value or "").strip())
    cleaned = re.sub(r"\s+", "_", cleaned)
    cleaned = cleaned.rstrip(" .")
    cleaned = _MULTI_UNDERSCORE.sub("_", cleaned).strip("_")
    if not cleaned:
        cleaned = _MULTI_UNDERSCORE.sub("_", _FS_INVALID_CHARS.sub("_", fallback).strip("_. ")) or "unknown"
    return cleaned[:80]


def _build_output_name(source_file: str) -> str:
    stem = _sanitize_segment(Path(source_file).stem, fallback="bom")
    ts = datetime.now().strftime("%Y%m%d%H%M%S")
    return f"admin_template_{stem}_{ts}.xlsx"


def write_admin_template(
    rows: list[dict],
    source_file: str,
    output_dir: str = "",
    company_name: str = "",
) -> str:
    root = Path(output_dir) if output_dir else OUTPUT_ROOT
    month = datetime.now().strftime("%Y-%m")
    company_seg = _sanitize_segment(company_name, fallback=Path(source_file).stem or "unknown")
    target_dir = root / month / company_seg
    target_dir.mkdir(parents=True, exist_ok=True)

    output_name = _build_output_name(source_file)
    output_path = (target_dir / output_name).resolve()
    shutil.copy2(str(TEMPLATE_PATH), str(output_path))

    wb = load_workbook(str(output_path))
    ws = wb.active

    for row_idx, row_data in enumerate(rows, start=2):
        for col_idx, key in enumerate(FIELD_KEYS, start=1):
            value = row_data.get(key, "")
            ws.cell(row=row_idx, column=col_idx, value=value)

    wb.save(str(output_path))
    wb.close()
    return str(output_path)
