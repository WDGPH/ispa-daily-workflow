from __future__ import annotations

import polars as pl

from panorama_compliance.schema.registry import resolve_dataset_schema


def dataset_field_names(dataset_id: str, *, schema_root) -> tuple[str, ...]:
    schema = resolve_dataset_schema(dataset_id, schema_root=schema_root)
    return schema.field_names


def project_to_dataset(
    df: pl.DataFrame,
    dataset_id: str,
    *,
    schema_root,
) -> pl.DataFrame:
    columns = list(dataset_field_names(dataset_id, schema_root=schema_root))
    output = df
    for column in columns:
        if column not in output.columns:
            output = output.with_columns(pl.lit(None).alias(column))
    return output.select(columns)
