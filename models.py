from typing import Any, Literal

from pydantic import BaseModel, Field


class AdminTemplateRow(BaseModel):
    customer_part_no: str = ""
    customer_product_name: str = ""
    product_model: str = ""
    product_name: str = ""
    brand: str = ""
    quantity: str = ""
    remark_customer: str = ""
    remark_supply_chain: str = ""
    customer_project_no: str = ""
    customer_material_no: str = ""
    inventory_feature: str = ""
    major_category: str = ""
    minor_category: str = ""
    supply_org: str = ""
    attachment_filename: str = ""
    remark_purchase: str = ""
    customer_expected_delivery: str = ""
    customer_expected_price: str = ""
    warehouse_factory: str = ""
    sales_unit_price_tax: str = ""
    shipment_date: str = ""


class ErrorItem(BaseModel):
    row: int | None = None
    field: str | None = None
    code: str
    message: str


class ConfirmationItem(BaseModel):
    row: int | None = None
    field: str | None = None
    reason: str
    suggested_value: str | None = None


class WarningItem(BaseModel):
    row: int | None = None
    message: str


class AnalyzeBomResult(BaseModel):
    result_id: str
    task_id: str | None = None
    parent_task_id: str | None = None
    status: Literal["success", "partial", "failed"]
    summary: str
    rows: list[AdminTemplateRow] = Field(default_factory=list)
    errors: list[ErrorItem] = Field(default_factory=list)
    needs_confirmation: list[ConfirmationItem] = Field(default_factory=list)
    warnings: list[WarningItem] = Field(default_factory=list)
    excel_output_path: str | None = None


# --- 持久化模型 ---

class TaskRecord(BaseModel):
    task_id: str
    parent_task_id: str | None = None
    task_type: Literal["analysis", "edit"]
    status: Literal["pending", "running", "success", "partial", "failed"]
    company_name: str | None = None
    source_label: str | None = None
    user_instruction: str = ""
    summary: str = ""
    row_count: int = 0
    metadata_json: str | None = None
    created_at: str
    updated_at: str


class ArtifactRecord(BaseModel):
    artifact_id: str
    task_id: str
    artifact_type: Literal["source", "normalized_bom", "excel"]
    version: int = 1
    storage_key: str
    file_name: str
    content_type: str
    metadata_json: str | None = None
    created_at: str


# --- 编辑/查询模型 ---

class BomEditOperation(BaseModel):
    row_index: int = Field(ge=1)
    field: str
    new_value: Any = ""


class BomLookupFilters(BaseModel):
    company_name: str | None = None
    task_type: str | None = None
    status: str | None = None
    date_from: str | None = None
    date_to: str | None = None
    keywords: list[str] = Field(default_factory=list)
    limit: int = Field(default=10, ge=1, le=50)
