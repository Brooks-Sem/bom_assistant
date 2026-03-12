import shutil
from datetime import datetime
from pathlib import Path

from openpyxl import load_workbook

TEMPLATE_PATH = Path(__file__).parent / "admin_template.xlsx"

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


def _build_output_name(source_file: str) -> str:
    stem = Path(source_file).stem
    ts = datetime.now().strftime("%Y%m%d%H%M%S")
    return f"admin_template_{stem}_{ts}.xlsx"


def write_admin_template(rows: list[dict], source_file: str, output_dir: str = "output") -> str:
    Path(output_dir).mkdir(parents=True, exist_ok=True)

    output_name = _build_output_name(source_file)
    output_path = str(Path(output_dir) / output_name)
    shutil.copy2(str(TEMPLATE_PATH), output_path)

    wb = load_workbook(output_path)
    ws = wb.active

    for row_idx, row_data in enumerate(rows, start=2):
        for col_idx, key in enumerate(FIELD_KEYS, start=1):
            value = row_data.get(key, "")
            ws.cell(row=row_idx, column=col_idx, value=value)

    wb.save(output_path)
    wb.close()
    return output_path
