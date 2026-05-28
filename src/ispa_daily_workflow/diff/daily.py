from __future__ import annotations

import re
from pathlib import Path

import polars as pl

from ispa_daily_workflow.compliance_history import (
    derive_active_noncompliant,
    project_schema_columns,
    read_compliance_history_frame,
)
from ispa_daily_workflow.io.readers import (
    read_dataframe,
    read_dataframe_with_schema,
    read_header,
)
from ispa_daily_workflow.models import DiffResult
from ispa_daily_workflow.schema import (
    ValidationError,
    apply_schema_types,
    resolve_dataset_schema,
    validate_exact_headers,
    validate_required_non_null,
)
from ispa_daily_workflow.validation.identity import (
    ensure_unique_identifier,
    normalize_key_column,
    sample_key_values,
    subset_difference,
)
from ispa_daily_workflow.validation.temporal import (
    parse_date_token,
    require_increasing_date_range,
)

FILENAME_PATTERN = re.compile(
    r"(?P<date>\d{8})_panorama_(?P<slice>.+)_noncompliant\.(?P<ext>xlsx|parquet)$"
)
COMPLIANCE_HISTORY_PATTERN = re.compile(
    r"(?P<date>\d{8})_panorama_(?P<slice>.+)_compliance_history\.(?P<ext>xlsx|parquet)$"
)


def _parse_date_and_slice(path: Path) -> tuple[str, str | None]:
    match = FILENAME_PATTERN.match(path.name)
    if match:
        return match.group("date"), match.group("slice")
    return path.name[:8], None


def _read_frame(
    path: Path,
    *,
    schema_root: Path | None = None,
    dataset_id: str | None = None,
    strict_headers: bool = True,
) -> pl.DataFrame:
    suffix = path.suffix.lower()
    if suffix == ".parquet":
        frame = pl.read_parquet(path)
        if schema_root is None or dataset_id is None:
            return frame
        schema = resolve_dataset_schema(dataset_id, schema_root=schema_root)
        if strict_headers:
            validate_exact_headers(list(frame.columns), schema, path.name)
        typed = apply_schema_types(frame, schema)
        validate_required_non_null(typed, schema, path.name)
        return typed
    if suffix in {".xlsx", ".xls"}:
        file_format = path.suffix.lstrip(".")
        if schema_root is not None and dataset_id is not None:
            schema = resolve_dataset_schema(dataset_id, schema_root=schema_root)
            return read_dataframe_with_schema(
                path,
                schema,
                file_format=file_format,
                as_string=True,
            )
        header = read_header(path, file_format)
        return read_dataframe(
            path,
            file_format=file_format,
            schema_overrides={name: pl.String() for name in header if name},
        )
    raise ValueError(f"Unsupported diff input format: {path}")


def _write_subset_violation_report(
    *,
    current_df: pl.DataFrame,
    current_only_ids: pl.DataFrame,
    output_dir: Path,
    current_date: str,
    previous_date: str,
    slice_token: str,
) -> Path:
    keep = [
        column
        for column in ("client_id", "school_id", "school_name", "source_file")
        if column in current_df.columns
    ]
    details = (
        current_df.join(current_only_ids, on="client_id", how="inner")
        .select(keep)
        .unique()
        .sort("client_id")
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = (
        output_dir
        / f"{current_date}_{previous_date}_panorama_{slice_token}_current_only_ids.csv"
    )
    details.write_csv(report_path)
    return report_path


def run_daily_diff(
    *,
    previous_path: Path,
    current_path: Path,
    output_dir: Path,
    schema_root: Path,
    enforce_subset: bool = True,
    formats: tuple[str, ...] = ("parquet",),
    strict_headers: bool = True,
) -> DiffResult:
    previous_df = _read_frame(
        previous_path,
        schema_root=schema_root,
        dataset_id="processed.panorama.noncompliant",
        strict_headers=strict_headers,
    )
    current_df = _read_frame(
        current_path,
        schema_root=schema_root,
        dataset_id="processed.panorama.noncompliant",
        strict_headers=strict_headers,
    )
    previous_date, previous_slice = _parse_date_and_slice(previous_path)
    current_date, current_slice = _parse_date_and_slice(current_path)
    slice_token = current_slice or previous_slice or "unknown"

    previous_df = normalize_key_column(
        previous_df,
        key="client_id",
        label=previous_path.name,
    )
    current_df = normalize_key_column(
        current_df,
        key="client_id",
        label=current_path.name,
    )
    ensure_unique_identifier(previous_df, key="client_id", label=previous_path.name)
    ensure_unique_identifier(current_df, key="client_id", label=current_path.name)

    current_ids = current_df.select("client_id").unique()

    became_compliant = previous_df.join(current_ids, on="client_id", how="anti")
    current_only = subset_difference(
        current_df,
        previous_df,
        key="client_id",
        subset_label=current_path.name,
        superset_label=previous_path.name,
    )

    if enforce_subset and current_only.height:
        report_path = _write_subset_violation_report(
            current_df=current_df,
            current_only_ids=current_only.select("client_id").unique(),
            output_dir=output_dir,
            current_date=current_date,
            previous_date=previous_date,
            slice_token=slice_token,
        )
        sample_ids = sample_key_values(current_only, key="client_id")
        raise ValidationError(
            "Current list includes client_id values not present in previous list "
            f"({current_only.height} rows). "
            f"Sample client_id values: {sample_ids}. "
            f"Review file: {report_path}"
        )

    became_compliant = project_schema_columns(
        became_compliant,
        schema_root=schema_root,
        dataset_id="processed.panorama.became_compliant",
    )

    output_dir.mkdir(parents=True, exist_ok=True)
    base = (
        output_dir
        / f"{current_date}_{previous_date}_panorama_{slice_token}_became_compliant"
    )
    written: Path | None = None
    if "parquet" in formats:
        written = base.with_suffix(".parquet")
        became_compliant.write_parquet(written)
    if "xlsx" in formats:
        written = base.with_suffix(".xlsx")
        became_compliant.write_excel(written)

    assert written is not None
    return DiffResult(
        current_date=current_date,
        previous_date=previous_date,
        slice_token=slice_token,
        became_compliant_rows=became_compliant.height,
        current_only_rows=current_only.height,
        output_path=written,
    )


def run_daily_diff_from_compliance_history(
    *,
    compliance_history_path: Path,
    run_date: str,
    previous_date: str,
    output_dir: Path,
    schema_root: Path,
    enforce_subset: bool = True,
    formats: tuple[str, ...] = ("parquet",),
    strict_headers: bool = True,
) -> DiffResult:
    run_day = parse_date_token(run_date, field_name="run_date")
    previous_day = parse_date_token(previous_date, field_name="previous_date")
    require_increasing_date_range(
        start_date=previous_day,
        end_date=run_day,
        start_label="previous_date",
        end_label="run_date",
        context="daily diff from compliance_history",
    )

    compliance_history_df = read_compliance_history_frame(
        compliance_history_path,
        schema_root=schema_root,
        strict_headers=strict_headers,
    )
    match = COMPLIANCE_HISTORY_PATTERN.match(compliance_history_path.name)
    slice_token = match.group("slice") if match else "unknown"

    previous_active = derive_active_noncompliant(
        compliance_history_df, as_of_date=previous_day
    )
    current_active = derive_active_noncompliant(
        compliance_history_df, as_of_date=run_day
    )

    current_ids = current_active.select("client_id").unique()

    became_compliant = previous_active.join(current_ids, on="client_id", how="anti")
    current_only = subset_difference(
        current_active,
        previous_active,
        key="client_id",
        subset_label=f"current_active {slice_token}",
        superset_label=f"previous_active {slice_token}",
    )

    if enforce_subset and current_only.height:
        report_path = _write_subset_violation_report(
            current_df=current_active,
            current_only_ids=current_only.select("client_id").unique(),
            output_dir=output_dir,
            current_date=run_date,
            previous_date=previous_date,
            slice_token=slice_token,
        )
        sample_ids = sample_key_values(current_only, key="client_id")
        raise ValidationError(
            "Current list includes client_id values not present in previous list "
            f"({current_only.height} rows). "
            f"Sample client_id values: {sample_ids}. "
            f"Review file: {report_path}"
        )

    became_compliant = project_schema_columns(
        became_compliant,
        schema_root=schema_root,
        dataset_id="processed.panorama.became_compliant",
    )

    output_dir.mkdir(parents=True, exist_ok=True)
    base = (
        output_dir
        / f"{run_date}_{previous_date}_panorama_{slice_token}_became_compliant"
    )
    written: Path | None = None
    if "parquet" in formats:
        written = base.with_suffix(".parquet")
        became_compliant.write_parquet(written)
    if "xlsx" in formats:
        written = base.with_suffix(".xlsx")
        became_compliant.write_excel(written)

    assert written is not None
    return DiffResult(
        current_date=run_date,
        previous_date=previous_date,
        slice_token=slice_token,
        became_compliant_rows=became_compliant.height,
        current_only_rows=current_only.height,
        output_path=written,
    )
