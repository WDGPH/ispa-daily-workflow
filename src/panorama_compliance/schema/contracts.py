from __future__ import annotations

import polars as pl

from panorama_compliance.schema.registry import resolve_dataset_schema
from panorama_compliance.schema.validation import (
    apply_schema_types,
    validate_exact_headers,
    validate_required_non_null,
    validate_unique_key,
)


def validate_dataset_contract(
    df: pl.DataFrame,
    *,
    dataset_id: str,
    label: str,
    schema_root,
    unique_key: str | None = None,
) -> pl.DataFrame:
    schema = resolve_dataset_schema(dataset_id, schema_root=schema_root)
    validate_exact_headers(df.columns, schema, label)
    typed = apply_schema_types(df, schema)
    validate_required_non_null(typed, schema, label)
    if unique_key:
        validate_unique_key(typed, unique_key, label)
    return typed
