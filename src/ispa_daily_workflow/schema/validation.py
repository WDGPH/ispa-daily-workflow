from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import polars as pl

from ispa_daily_workflow.schema.errors import ValidationError


@dataclass(frozen=True)
class DataQualityIssue:
    code: str
    message: str


@dataclass(frozen=True)
class LoadedSchema:
    path: Path
    name: str
    field_names: tuple[str, ...]
    required: tuple[str, ...]
    type_map: dict[str, str]


def load_schema(schema_root: Path, filename: str) -> LoadedSchema:
    path = schema_root / filename
    if not path.exists():
        raise FileNotFoundError(f"Schema not found: {path}")

    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)

    fields = payload.get("fields")
    if not isinstance(fields, list) or not fields:
        raise ValidationError(f"Schema has no fields: {path}")

    names: list[str] = []
    required: list[str] = []
    type_map: dict[str, str] = {}
    for field in fields:
        if not isinstance(field, dict) or "name" not in field:
            raise ValidationError(f"Invalid schema field in {path}: {field!r}")
        name = str(field["name"])
        names.append(name)
        type_map[name] = str(field.get("type", "string"))
        constraints = field.get("constraints")
        if isinstance(constraints, dict) and constraints.get("required") is True:
            required.append(name)

    return LoadedSchema(
        path=path,
        name=str(payload.get("name", filename)),
        field_names=tuple(names),
        required=tuple(required),
        type_map=type_map,
    )


def schema_field_names(schema: LoadedSchema) -> tuple[str, ...]:
    return schema.field_names


def required_fields(schema: LoadedSchema) -> tuple[str, ...]:
    return schema.required


def validate_exact_headers(
    columns: list[str] | tuple[str, ...], schema: LoadedSchema, label: str
) -> None:
    observed = tuple(str(col).strip() for col in columns)
    expected = schema.field_names
    if observed != expected:
        missing = [name for name in expected if name not in observed]
        extra = [name for name in observed if name not in expected]
        raise ValidationError(
            f"{label}: header mismatch for schema {schema.name}. "
            f"Missing={missing or '[]'} Extra={extra or '[]'}"
        )


def _cast_expr(column: str, data_type: str) -> pl.Expr:
    if data_type == "string":
        return pl.col(column).cast(pl.Utf8).str.strip_chars().alias(column)
    if data_type == "boolean":
        return pl.col(column).cast(pl.Boolean, strict=False).alias(column)
    if data_type == "integer":
        return pl.col(column).cast(pl.Int64, strict=False).alias(column)
    if data_type == "number":
        return pl.col(column).cast(pl.Float64, strict=False).alias(column)
    if data_type == "date":
        return pl.col(column).cast(pl.Date, strict=False).alias(column)
    return pl.col(column).alias(column)


def apply_schema_types(df: pl.DataFrame, schema: LoadedSchema) -> pl.DataFrame:
    exprs = []
    for column in schema.field_names:
        if column in df.columns:
            exprs.append(_cast_expr(column, schema.type_map.get(column, "string")))
    if not exprs:
        return df
    return df.with_columns(exprs)


def validate_required_non_null(
    df: pl.DataFrame, schema: LoadedSchema, label: str
) -> None:
    for column in schema.required:
        if column not in df.columns:
            raise ValidationError(f"{label}: missing required column {column}")
        null_count = df.select(pl.col(column).is_null().sum()).item()
        blank_count = (
            df.select(
                pl.when(
                    pl.col(column).cast(pl.Utf8, strict=False).str.strip_chars() == ""
                )
                .then(1)
                .otherwise(0)
                .sum()
            ).item()
            if schema.type_map.get(column) == "string"
            else 0
        )
        if int(null_count) + int(blank_count) > 0:
            raise ValidationError(
                f"{label}: required column {column} has {int(null_count) + int(blank_count)} null/blank rows"
            )


def validate_unique_key(df: pl.DataFrame, key: str, label: str) -> None:
    if key not in df.columns:
        raise ValidationError(f"{label}: key column not found: {key}")
    duplicates = (
        df.group_by(key).len().filter(pl.col("len") > 1).select(pl.len()).item()
    )
    if int(duplicates) > 0:
        raise ValidationError(
            f"{label}: duplicate values in {key} ({int(duplicates)} keys)"
        )


def validate_subset(
    subset_df: pl.DataFrame,
    superset_df: pl.DataFrame,
    key: str,
    *,
    subset_label: str,
    superset_label: str,
) -> None:
    if key not in subset_df.columns or key not in superset_df.columns:
        raise ValidationError(
            f"Subset check requires key {key} in both datasets ({subset_label}, {superset_label})"
        )
    outside = (
        subset_df.select(key)
        .unique()
        .join(
            superset_df.select(key).unique(),
            on=key,
            how="anti",
        )
    )
    if outside.height:
        raise ValidationError(
            f"Subset check failed: {subset_label} contains {outside.height} keys not in {superset_label}"
        )


def validate_headers_and_quality(
    df: pl.DataFrame,
    *,
    schema: LoadedSchema,
    label: str,
    unique_key: str | None = None,
) -> pl.DataFrame:
    validate_exact_headers(df.columns, schema, label)
    typed = apply_schema_types(df, schema)
    validate_required_non_null(typed, schema, label)
    if unique_key:
        validate_unique_key(typed, unique_key, label)
    return typed
