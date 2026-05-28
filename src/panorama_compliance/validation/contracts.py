from __future__ import annotations

import polars as pl

from panorama_compliance.domain.delivery.contracts import (  # noqa: F401
    DELIVERY_DATASET_BY_OUTPUT_ID as DELIVERY_SCHEMA_BY_OUTPUT_ID,
    project_delivery_contract,
)
from panorama_compliance.validation.catalog import RULE_DELIVERY_CONTRACT_ID
from panorama_compliance.schema import ValidationError


DELIVERY_REPORT_REQUIRED_COLUMNS = {
    "sharepoint.overdue.pdf": (
        "school_label",
        "last_name",
        "first_name",
        "date_of_birth",
    ),
    "sharepoint.suspension.pdf": (
        "school_label",
        "last_name",
        "first_name",
        "date_of_birth",
        "compliant",
    ),
}

__all__ = [
    "DELIVERY_REPORT_REQUIRED_COLUMNS",
    "DELIVERY_SCHEMA_BY_OUTPUT_ID",
    "project_delivery_contract",
    "validate_report_delivery_contract",
]


def validate_report_delivery_contract(frame: pl.DataFrame, *, output_id: str) -> None:
    required = DELIVERY_REPORT_REQUIRED_COLUMNS.get(output_id)
    if required is None:
        raise ValueError(f"No report contract is registered for output_id={output_id}")
    missing = [column for column in required if column not in frame.columns]
    if missing:
        raise ValidationError(
            "VALIDATION FAIL "
            f"[{RULE_DELIVERY_CONTRACT_ID}] "
            f"delivery report contract failed for {output_id}: missing required columns {missing}"
        )
