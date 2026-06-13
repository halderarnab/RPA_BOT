from __future__ import annotations

from pathlib import Path
from typing import Any


MANDATORY_FIELDS = {
    "procurement": [
        "finance_year",
        "source_of_waste_tyre",
        "supplier_name",
        "contact_details",
        "supplier_address",
        "raw_material_type",
        "quantity_received_tonnes",
        "invoice_number",
        "supplier_gst",
        "purchase_date",
        "invoice_file",
    ],
    "recycling": [
        "finance_year",
        "source_of_waste_tyre",
        "recycled_material_type",
        "quantity_processed_mt",
        "recycled_date",
    ],
    "sales": [
        "sales_date",
        "invoice_number",
        "e_invoice_number",
        "buyer_name",
        "hsn_code",
        "principal_amount_rs",
        "quantity_sold_kg",
        "buyer_address",
        "invoice_file",
        "end_product_table",
    ],
}


def validate_row(dataset: str, row: dict[str, Any], invoice_folder: Path | None) -> list[str]:
    errors: list[str] = []
    for field in MANDATORY_FIELDS[dataset]:
        value = row.get(field)
        if value is None or str(value).strip() == "":
            errors.append(f"{dataset} : Missing mandatory field in excel file: {field}")

    invoice_file = row.get("invoice_file")
    if invoice_file and invoice_folder is not None:
        invoice_path = invoice_folder / str(invoice_file).strip()
        if not invoice_path.exists():
            errors.append(f"Invoice PDF not found: {invoice_path}")

    return errors
