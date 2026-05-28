from __future__ import annotations

from pathlib import Path

import polars as pl

from panorama_compliance.io.readers import read_header
from panorama_compliance.schema import LoadedSchema, validate_exact_headers
from panorama_compliance.validation.identity import ensure_unique_identifier


def landing_identifier_expr(column: str) -> pl.Expr:
    cleaned = pl.col(column).cast(pl.Utf8).str.strip_chars().str.replace(r"\.0$", "")
    return pl.when(cleaned == "").then(None).otherwise(cleaned).alias(column)


def validate_landing_headers(
    file_path: Path,
    landing_schema: LoadedSchema,
    *,
    strict_headers: bool = True,
) -> None:
    if not strict_headers:
        return
    header = read_header(file_path, file_path.suffix.lstrip("."))
    validate_exact_headers(header, landing_schema, file_path.name)


def normalize_landing_identifier_columns(frame: pl.DataFrame) -> pl.DataFrame:
    exprs = [landing_identifier_expr("Client ID")]
    if "Ontario Immunization ID" in frame.columns:
        exprs.append(landing_identifier_expr("Ontario Immunization ID"))
    return frame.with_columns(exprs)


def ensure_no_duplicate_client_ids(frame: pl.DataFrame, *, label: str) -> None:
    if "client_id" not in frame.columns:
        return
    ensure_unique_identifier(frame, key="client_id", label=label)
