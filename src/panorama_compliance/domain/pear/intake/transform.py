from __future__ import annotations

import re
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import polars as pl

from panorama_compliance.reference import SchoolReference, parse_school_name_and_id
from panorama_compliance.schema import (
    ValidationError,
    apply_schema_types,
    resolve_dataset_schema,
    validate_exact_headers,
    validate_required_non_null,
    validate_unique_key,
)
from panorama_compliance.validation import (
    RULE_PEAR_WAVE_WINDOW_AUTHORITY_ID,
    require_wave_window_authority,
)

from .constants import (
    CLIENT_ID_PATTERN,
    LANDING_SCHEMA_BY_REPORT,
    PROCESSED_SCHEMA_BY_REPORT,
    REPORT_OVERDUE,
    REPORT_SUSPENSION,
    REPORT_SUSPENSION_VS_OVERDUE,
)
from .models import LandingReport, ProcessedReport, WaveWindow
from .naming import resolve_suspension_canonical_filename
from .primitives import is_blank_value, parse_date_optional, parse_date_required


def validate_landing_schema(
    landing: LandingReport,
    schema_root: Path,
    *,
    strict_headers: bool = True,
) -> None:
    schema = resolve_dataset_schema(
        LANDING_SCHEMA_BY_REPORT[landing.report_type],
        schema_root=schema_root,
    )
    if strict_headers:
        validate_exact_headers(
            list(landing.landing_frame.columns),
            schema,
            label=f"{landing.path.name} ({landing.report_type}) landing",
        )
    typed = apply_schema_types(landing.landing_frame, schema)
    validate_required_non_null(
        typed,
        schema,
        label=f"{landing.path.name} ({landing.report_type}) landing",
    )
    # Overdue duplicates are handled as a downstream transform warning with
    # deterministic dedupe before processed output validation.
    if landing.report_type != REPORT_OVERDUE:
        client_column = _landing_client_column(landing.report_type)
        validate_unique_key(
            typed,
            key=client_column,
            label=f"{landing.path.name} ({landing.report_type}) landing",
        )


def validate_processed_schema(
    processed: ProcessedReport,
    schema_root: Path,
    *,
    strict_headers: bool = True,
) -> None:
    schema = resolve_dataset_schema(
        PROCESSED_SCHEMA_BY_REPORT[processed.landing.report_type],
        schema_root=schema_root,
    )
    if strict_headers:
        validate_exact_headers(
            list(processed.processed_frame.columns),
            schema,
            label=f"{processed.landing.path.name} ({processed.landing.report_type}) processed",
        )
    typed = apply_schema_types(processed.processed_frame, schema)
    validate_required_non_null(
        typed,
        schema,
        label=f"{processed.landing.path.name} ({processed.landing.report_type}) processed",
    )
    validate_unique_key(
        typed,
        key="client_id",
        label=f"{processed.landing.path.name} ({processed.landing.report_type}) processed",
    )
    invalid = typed.filter(
        pl.col("client_id")
        .cast(pl.String, strict=False)
        .str.strip_chars()
        .str.contains(r"^[0-9]{10}$")
        .not_()
    )
    if invalid.height:
        raise ValidationError(
            f"{processed.landing.path.name} ({processed.landing.report_type}) processed: "
            f"{invalid.height} rows failed client_id 10-digit validation"
        )


def transform_report(
    landing: LandingReport,
    *,
    reference: SchoolReference,
    wave_windows: dict[str, WaveWindow] | None = None,
) -> ProcessedReport:
    warnings: list[str] = list(landing.warnings)

    if landing.report_type == REPORT_SUSPENSION:
        canonical_filename, suffix, suffix_warning = (
            resolve_suspension_canonical_filename(
                landing,
                reference=reference,
            )
        )
        if suffix_warning:
            warnings.append(suffix_warning)
        if canonical_filename != landing.canonical_filename:
            warnings.append(
                "Suspension canonical filename suffix was derived from school reference "
                f"levels ({suffix}) instead of title text"
            )
        processed = _transform_suspension(landing, reference)
        return ProcessedReport(
            landing=landing,
            processed_frame=processed,
            canonical_filename=canonical_filename,
            report_warnings=tuple(warnings),
        )

    if landing.report_type == REPORT_SUSPENSION_VS_OVERDUE:
        resolved_wave_windows = (
            wave_windows
            if wave_windows is not None
            else require_wave_window_authority(
                reference=reference,
                context=f"{landing.path.name} suspension-vs-overdue transform",
                rule_id=RULE_PEAR_WAVE_WINDOW_AUTHORITY_ID,
            )
        )
        processed, no_action_count, extra_warnings = _transform_suspension_vs_overdue(
            landing,
            reference=reference,
            wave_windows=resolved_wave_windows,
        )
        warnings.extend(extra_warnings)
        return ProcessedReport(
            landing=landing,
            processed_frame=processed,
            canonical_filename=landing.canonical_filename,
            report_warnings=tuple(warnings),
            no_action_count=no_action_count,
        )

    if landing.report_type == REPORT_OVERDUE:
        processed, extra_warnings = _transform_overdue(landing, reference)
        warnings.extend(extra_warnings)
        return ProcessedReport(
            landing=landing,
            processed_frame=processed,
            canonical_filename=landing.canonical_filename,
            report_warnings=tuple(warnings),
        )

    raise ValidationError(
        f"{landing.path.name}: unsupported report type {landing.report_type}"
    )


def _transform_suspension(
    landing: LandingReport, reference: SchoolReference
) -> pl.DataFrame:
    records: list[list[Any]] = []
    fill_school_name: Any = None

    for row in landing.source_rows:
        school_name_raw = row["School Name"]
        if not is_blank_value(school_name_raw):
            fill_school_name = school_name_raw
        if is_blank_value(fill_school_name):
            raise ValidationError(
                f"{landing.path.name}: suspension row has blank School Name after fill-down"
            )

        school_name, school_id, _level, _wave = _resolve_school(
            fill_school_name, reference, landing.path
        )
        records.append(
            [
                _normalize_client_id(row["Client Id"], landing.path),
                school_id,
                school_name,
                _normalize_text(row["First Name"]),
                _normalize_text(row["Last Name"]),
                parse_date_required(
                    row["Date of Birth"], landing.path, "Date of Birth"
                ),
                parse_date_optional(
                    row["Suspension Rescind Date"],
                    landing.path,
                    "Suspension Rescind Date",
                ),
            ]
        )

    return pl.DataFrame(
        records,
        schema=[
            "client_id",
            "school_id",
            "school_name",
            "first_name",
            "last_name",
            "date_of_birth",
            "rescind_date",
        ],
        orient="row",
    )


def _transform_suspension_vs_overdue(
    landing: LandingReport,
    *,
    reference: SchoolReference,
    wave_windows: dict[str, WaveWindow],
) -> tuple[pl.DataFrame, int, list[str]]:
    records: list[list[Any]] = []
    warnings: list[str] = []
    no_action_count = 0

    for row in landing.source_rows:
        school_name, school_id, _level, wave = _resolve_school(
            row["School Name"], reference, landing.path
        )
        wave_window = wave_windows.get(wave)
        if wave_window is None:
            raise ValidationError(
                f"VALIDATION FAIL [{RULE_PEAR_WAVE_WINDOW_AUTHORITY_ID}] "
                f"{landing.path.name}: missing suspension window metadata for wave={wave}"
            )
        action_required, action_date = _derive_action(
            report_date=landing.footer.report_date,
            wave_window=wave_window,
        )
        if action_required == "no_action":
            no_action_count += 1
            if landing.footer.report_date > wave_window.suspension_window_end:
                warnings.append(
                    "Rows were classified as no_action because report_date is after suspension_window_end"
                )
            continue

        records.append(
            [
                _normalize_client_id(row["ClientID"], landing.path),
                school_id,
                school_name,
                _normalize_text(row["First Name"]),
                _normalize_text(row["Last Name"]),
                parse_date_required(
                    row["Date of Birth"], landing.path, "Date of Birth"
                ),
                action_required,
                action_date,
            ]
        )

    frame = pl.DataFrame(
        records,
        schema={
            "client_id": pl.Utf8,
            "school_id": pl.Utf8,
            "school_name": pl.Utf8,
            "first_name": pl.Utf8,
            "last_name": pl.Utf8,
            "date_of_birth": pl.Date,
            "action_required": pl.Utf8,
            "action_date": pl.Date,
        },
        orient="row",
    )
    return frame, no_action_count, warnings


def _transform_overdue(
    landing: LandingReport,
    reference: SchoolReference,
) -> tuple[pl.DataFrame, list[str]]:
    records: list[list[Any]] = []
    warnings: list[str] = []
    for row in landing.source_rows:
        school_name, school_id, _level, _wave = _resolve_school(
            row["School Name"], reference, landing.path
        )
        records.append(
            [
                _normalize_client_id(row["Remaining Overdue"], landing.path),
                school_id,
                school_name,
                _normalize_text(row["First Name"]),
                _normalize_text(row["Last Name"]),
                parse_date_required(
                    row["Date of Birth"], landing.path, "Date of Birth"
                ),
                _normalize_agents(row["Repeater"]),
            ]
        )

    frame = pl.DataFrame(
        records,
        schema=[
            "client_id",
            "school_id",
            "school_name",
            "first_name",
            "last_name",
            "date_of_birth",
            "overdue_agents",
        ],
        orient="row",
    )
    duplicate_keys = (
        frame.group_by("client_id").len().filter(pl.col("len") > 1).sort("client_id")
    )
    if duplicate_keys.height:
        duplicate_ids = [str(value) for value in duplicate_keys.get_column("client_id")]
        duplicate_rows = int(duplicate_keys.get_column("len").sum())
        removed_rows = duplicate_rows - duplicate_keys.height
        frame = frame.unique(subset=["client_id"], keep="first", maintain_order=True)
        warnings.append(
            "Overdue duplicate client_id rows were removed before processed output: "
            f"duplicate_keys={duplicate_keys.height} "
            f"removed_rows={removed_rows} "
            f"client_ids=[{', '.join(duplicate_ids)}]"
        )
    return frame, warnings


def _landing_client_column(report_type: str) -> str:
    if report_type == REPORT_SUSPENSION:
        return "Client Id"
    if report_type == REPORT_SUSPENSION_VS_OVERDUE:
        return "ClientID"
    if report_type == REPORT_OVERDUE:
        return "Remaining Overdue"
    raise ValidationError(f"Unsupported report type: {report_type}")


def _resolve_school(
    school_name_raw: Any,
    reference: SchoolReference,
    source_path: Path,
) -> tuple[str, str, str, str]:
    school_name, school_id = parse_school_name_and_id(school_name_raw, None)
    if not school_id:
        raise ValidationError(
            f"{source_path.name}: unable to parse school_id from School Name"
        )
    record = reference.by_id.get(school_id)
    if record is None:
        raise ValidationError(
            f"{source_path.name}: school_id {school_id} not found in school reference"
        )
    return record.school_name, school_id, record.level, record.wave


def _derive_action(
    *, report_date: date, wave_window: WaveWindow
) -> tuple[str, date | None]:
    if report_date < wave_window.applied_date:
        return "no_action", None
    rescind_prewindow_start = wave_window.suspension_window_start - timedelta(days=1)
    if report_date < rescind_prewindow_start:
        return "delete", report_date
    if report_date < wave_window.suspension_window_start:
        return "rescind", report_date + timedelta(days=1)
    if report_date <= wave_window.suspension_window_end:
        return "rescind", report_date
    return "no_action", None


def _normalize_client_id(value: Any, source_path: Path) -> str:
    text = str(value).strip() if value is not None else ""
    if text.endswith(".0"):
        text = text[:-2]
    text = re.sub(r"\s+", "", text)
    if not CLIENT_ID_PATTERN.match(text):
        raise ValidationError(
            f"{source_path.name}: invalid client_id format (must be 10 digits)"
        )
    return text


def _normalize_text(value: Any) -> str:
    return str(value).strip().upper() if value is not None else ""


def _normalize_agents(value: Any) -> str | None:
    text = str(value).strip() if value is not None else ""
    if not text:
        return None
    parts = [segment.strip().upper() for segment in text.split(";") if segment.strip()]
    return "; ".join(parts) if parts else None


__all__ = [
    "WaveWindow",
    "validate_landing_schema",
    "validate_processed_schema",
    "transform_report",
    "_derive_action",
]
