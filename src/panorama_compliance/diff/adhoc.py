from __future__ import annotations

import re
from pathlib import Path

import polars as pl

from panorama_compliance.compliance_history import (
    derive_became_compliant,
    project_schema_columns,
    read_compliance_history_frame,
)
from panorama_compliance.io.readers import (
    read_dataframe,
    read_dataframe_with_schema,
    read_header,
)
from panorama_compliance.schema import (
    apply_schema_types,
    resolve_dataset_schema,
    validate_exact_headers,
    validate_required_non_null,
)
from panorama_compliance.validation.frames import filter_by_school_ids
from panorama_compliance.validation.identity import normalize_key_column
from panorama_compliance.validation.temporal import (
    parse_date_token,
    require_increasing_date_range,
)


def _read_frame(
    path: Path,
    *,
    schema_root: Path | None = None,
    dataset_id: str | None = None,
    strict_headers: bool = True,
) -> pl.DataFrame:
    if path.suffix.lower() == ".parquet":
        frame = pl.read_parquet(path)
        if schema_root is None or dataset_id is None:
            return frame
        schema = resolve_dataset_schema(dataset_id, schema_root=schema_root)
        if strict_headers:
            validate_exact_headers(list(frame.columns), schema, path.name)
        typed = apply_schema_types(frame, schema)
        validate_required_non_null(typed, schema, path.name)
        return typed
    if path.suffix.lower() in {".xlsx", ".xls"}:
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
    raise ValueError(f"Unsupported input format: {path}")


def _token_from_name(path: Path) -> str:
    match = re.match(r"(\d{8}).*", path.name)
    return match.group(1) if match else path.stem


def run_adhoc_diff(
    *,
    baseline_path: Path,
    delivery_path: Path,
    output_dir: Path,
    schema_root: Path,
    school_ids: set[str] | None = None,
    formats: tuple[str, ...] = ("parquet",),
    strict_headers: bool = True,
) -> Path:
    baseline_df = normalize_key_column(
        _read_frame(
            baseline_path,
            schema_root=schema_root,
            dataset_id="processed.panorama.noncompliant",
            strict_headers=strict_headers,
        ),
        key="client_id",
        label=baseline_path.name,
    )
    delivery_df = normalize_key_column(
        _read_frame(
            delivery_path,
            schema_root=schema_root,
            dataset_id="processed.panorama.noncompliant",
            strict_headers=strict_headers,
        ),
        key="client_id",
        label=delivery_path.name,
    )

    if school_ids:
        baseline_df = filter_by_school_ids(
            baseline_df,
            school_ids=school_ids,
            school_id_column="school_id",
        )
        delivery_df = filter_by_school_ids(
            delivery_df,
            school_ids=school_ids,
            school_id_column="school_id",
        )

    became_compliant = baseline_df.join(
        delivery_df.select("client_id").unique(),
        on="client_id",
        how="anti",
    )

    became_compliant = project_schema_columns(
        became_compliant,
        schema_root=schema_root,
        dataset_id="processed.panorama.became_compliant",
    )

    baseline_token = _token_from_name(baseline_path)
    delivery_token = _token_from_name(delivery_path)

    output_dir.mkdir(parents=True, exist_ok=True)
    base = (
        output_dir
        / f"{delivery_token}_{baseline_token}_panorama_adhoc_became_compliant"
    )

    written: Path | None = None
    if "parquet" in formats:
        written = base.with_suffix(".parquet")
        became_compliant.write_parquet(written)
    if "xlsx" in formats:
        written = base.with_suffix(".xlsx")
        became_compliant.write_excel(written)

    assert written is not None
    return written


def run_adhoc_diff_from_compliance_history(
    *,
    compliance_history_path: Path,
    baseline_date: str,
    delivery_date: str,
    output_dir: Path,
    schema_root: Path,
    school_ids: set[str] | None = None,
    formats: tuple[str, ...] = ("parquet",),
    strict_headers: bool = True,
) -> Path:
    baseline_day = parse_date_token(baseline_date, field_name="baseline_date")
    delivery_day = parse_date_token(delivery_date, field_name="delivery_date")
    require_increasing_date_range(
        start_date=baseline_day,
        end_date=delivery_day,
        start_label="baseline_date",
        end_label="delivery_date",
        context="adhoc diff from compliance_history",
    )

    compliance_history_df = read_compliance_history_frame(
        compliance_history_path,
        schema_root=schema_root,
        strict_headers=strict_headers,
    )
    became_compliant = derive_became_compliant(
        compliance_history_df,
        start_exclusive=baseline_day,
        end_inclusive=delivery_day,
    )

    if school_ids:
        became_compliant = filter_by_school_ids(
            became_compliant,
            school_ids=school_ids,
            school_id_column="school_id",
        )

    became_compliant = project_schema_columns(
        became_compliant,
        schema_root=schema_root,
        dataset_id="processed.panorama.became_compliant",
    )

    output_dir.mkdir(parents=True, exist_ok=True)
    base = (
        output_dir / f"{delivery_date}_{baseline_date}_panorama_adhoc_became_compliant"
    )

    written: Path | None = None
    if "parquet" in formats:
        written = base.with_suffix(".parquet")
        became_compliant.write_parquet(written)
    if "xlsx" in formats:
        written = base.with_suffix(".xlsx")
        became_compliant.write_excel(written)

    assert written is not None
    return written
