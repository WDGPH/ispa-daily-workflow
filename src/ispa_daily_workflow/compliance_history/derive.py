from __future__ import annotations

import re
from datetime import date
from pathlib import Path

import polars as pl

from ispa_daily_workflow.normalize.core import parse_date_value
from ispa_daily_workflow.schema import (
    LoadedSchema,
    ValidationError,
    apply_schema_types,
    resolve_dataset_schema,
    schema_field_names,
    validate_exact_headers,
    validate_required_non_null,
)
from ispa_daily_workflow.validation.evidence import (
    ParseFailureCounter,
    collect_date_parse_counters,
)
from ispa_daily_workflow.validation.identity import (
    ensure_unique_identifier,
    normalize_key_column,
)
from ispa_daily_workflow.validation.temporal import parse_date_token

COMPLIANCE_HISTORY_PATTERN = re.compile(
    r"(?P<date>\d{8})_panorama_(?P<slice>.+)_compliance_history\.(?P<ext>parquet)$"
)
DEFAULT_SCHEMA_ROOT = Path(__file__).resolve().parents[3] / "schema"


def parse_run_date(run_date: str) -> date:
    return parse_date_token(run_date, field_name="run_date")


def parse_slice_from_compliance_history(path: Path) -> str:
    match = COMPLIANCE_HISTORY_PATTERN.match(path.name)
    if not match:
        raise ValueError(
            f"Compliance History file does not match naming convention: {path.name}"
        )
    return match.group("slice")


def read_frame(
    path: Path,
    *,
    schema: LoadedSchema | None = None,
    strict_headers: bool = True,
) -> pl.DataFrame:
    if path.suffix.lower() == ".parquet":
        frame = pl.read_parquet(path)
        if schema is None:
            return frame
        if strict_headers:
            validate_exact_headers(list(frame.columns), schema, path.name)
        typed = apply_schema_types(frame, schema)
        validate_required_non_null(typed, schema, path.name)
        return typed
    raise ValueError(
        f"Unsupported compliance_history format: {path} (expected .parquet)"
    )


def normalize_compliance_history_frame(
    frame: pl.DataFrame, *, label: str
) -> pl.DataFrame:
    if "compliant" not in frame.columns:
        raise ValidationError(f"{label}: missing compliant")

    normalized = normalize_key_column(
        frame,
        key="client_id",
        label=label,
    ).with_columns(
        pl.col("compliant")
        .map_elements(parse_date_value, return_dtype=pl.Date)
        .alias("compliant"),
    )
    ensure_unique_identifier(normalized, key="client_id", label=label)
    return normalized


def read_compliance_history_frame(
    path: Path,
    *,
    schema_root: Path | None = None,
    strict_headers: bool = True,
    parse_counters_sink: list[ParseFailureCounter] | None = None,
) -> pl.DataFrame:
    resolved_schema_root = schema_root or DEFAULT_SCHEMA_ROOT
    compliance_history_schema = resolve_dataset_schema(
        "processed.panorama.suspension_compliance_history",
        schema_root=resolved_schema_root,
    )
    raw = read_frame(
        path,
        schema=compliance_history_schema,
        strict_headers=strict_headers,
    )
    if parse_counters_sink is not None:
        parse_counters_sink.extend(
            collect_date_parse_counters(
                raw,
                stream=path.name,
                fields=("date_of_birth", "compliant"),
            )
        )
    return normalize_compliance_history_frame(
        raw,
        label=path.name,
    )


def derive_active_noncompliant(
    compliance_history_df: pl.DataFrame, *, as_of_date: date
) -> pl.DataFrame:
    return compliance_history_df.filter(
        pl.col("compliant").is_null() | (pl.col("compliant") > pl.lit(as_of_date))
    )


def derive_became_compliant(
    compliance_history_df: pl.DataFrame,
    *,
    start_exclusive: date | None,
    end_inclusive: date,
) -> pl.DataFrame:
    condition = pl.col("compliant").is_not_null() & (
        pl.col("compliant") <= pl.lit(end_inclusive)
    )
    if start_exclusive is not None:
        condition = condition & (pl.col("compliant") > pl.lit(start_exclusive))
    return compliance_history_df.filter(condition)


def project_schema_columns(
    df: pl.DataFrame,
    *,
    schema_root: Path,
    dataset_id: str,
) -> pl.DataFrame:
    schema = resolve_dataset_schema(dataset_id, schema_root=schema_root)
    columns = list(schema_field_names(schema))
    frame = df
    for column in columns:
        if column not in frame.columns:
            frame = frame.with_columns(pl.lit(None).alias(column))
    frame = frame.select(columns)
    if "client_id" in frame.columns:
        ensure_unique_identifier(
            frame,
            key="client_id",
            label=f"schema projection {dataset_id}",
        )
    return frame


def write_output_base(
    frame: pl.DataFrame,
    *,
    output_base: Path,
    formats: tuple[str, ...],
) -> list[Path]:
    output_base.parent.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    if "parquet" in formats:
        parquet_path = output_base.with_suffix(".parquet")
        frame.write_parquet(parquet_path)
        written.append(parquet_path)
    if "xlsx" in formats:
        xlsx_path = output_base.with_suffix(".xlsx")
        frame.write_excel(xlsx_path)
        written.append(xlsx_path)
    if "csv" in formats:
        csv_path = output_base.with_suffix(".csv")
        frame.write_csv(csv_path)
        written.append(csv_path)
    return written


def discover_latest_compliance_history_by_slice(
    compliance_history_dir: Path, *, run_date: str | None = None
) -> dict[str, Path]:
    latest: dict[str, tuple[str, Path]] = {}
    for path in compliance_history_dir.glob("*_panorama_*_compliance_history.parquet"):
        match = COMPLIANCE_HISTORY_PATTERN.match(path.name)
        if not match:
            continue
        date_token = match.group("date")
        if run_date is not None and date_token > run_date:
            continue
        slice_token = match.group("slice")
        existing = latest.get(slice_token)
        if existing is None:
            latest[slice_token] = (date_token, path)
            continue
        existing_date, existing_path = existing
        if date_token > existing_date:
            latest[slice_token] = (date_token, path)
            continue
        if (
            date_token == existing_date
            and existing_path.suffix != ".parquet"
            and path.suffix == ".parquet"
        ):
            latest[slice_token] = (date_token, path)
    return {slice_token: path for slice_token, (_, path) in latest.items()}


def discover_compliance_history_by_slice_for_date(
    compliance_history_dir: Path,
    *,
    run_date: str,
) -> dict[str, Path]:
    selected: dict[str, Path] = {}
    for path in compliance_history_dir.glob("*_panorama_*_compliance_history.parquet"):
        match = COMPLIANCE_HISTORY_PATTERN.match(path.name)
        if not match:
            continue
        date_token = match.group("date")
        if date_token != run_date:
            continue
        slice_token = match.group("slice")
        existing = selected.get(slice_token)
        if existing is None or path.name < existing.name:
            selected[slice_token] = path
    return dict(sorted(selected.items()))
