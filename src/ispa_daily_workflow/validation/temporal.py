from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime

import polars as pl

from ispa_daily_workflow.schema import ValidationError
from ispa_daily_workflow.validation.catalog import (
    RULE_DATE_RANGE_ID,
    RULE_PEAR_RESCIND_WINDOW_START_ID,
    RULE_PREVIOUS_BUSINESS_DAY_ID,
    RULE_PREVIOUS_SCOPE_DATA_ID,
    RULE_TEMPORAL_BOUNDS_ID,
)
from ispa_daily_workflow.validation.models import RuleResult

_MIN_VALID_DATE = date(1900, 1, 1)
_RUN_DATE_FORMAT = "%Y%m%d"


@dataclass(frozen=True)
class TemporalPolicy:
    min_age_years: int = 4
    max_age_years: int = 17


def _sample_client_ids(frame: pl.DataFrame, *, limit: int = 20) -> list[str]:
    if "client_id" not in frame.columns:
        return []
    return [
        str(value)
        for value in frame.get_column("client_id").drop_nulls().head(limit).to_list()
    ]


def _all_client_ids(frame: pl.DataFrame) -> list[str]:
    if "client_id" not in frame.columns:
        return []
    ids = [str(value) for value in frame.get_column("client_id").drop_nulls().to_list()]
    return sorted({value for value in ids if value.strip()})


def _all_source_files(frame: pl.DataFrame) -> list[str]:
    if "source_file" not in frame.columns:
        return []
    source_files = [
        str(value) for value in frame.get_column("source_file").drop_nulls().to_list()
    ]
    return sorted({value for value in source_files if value.strip()})


def _client_id_source_rows(frame: pl.DataFrame) -> list[dict[str, str | None]]:
    if "client_id" not in frame.columns or "source_file" not in frame.columns:
        return []
    pairs = (
        frame.select(["client_id", "source_file"])
        .unique()
        .sort(["client_id", "source_file"])
        .to_dicts()
    )
    rows: list[dict[str, str | None]] = []
    for pair in pairs:
        client_id = pair.get("client_id")
        if client_id is None:
            continue
        source_file = pair.get("source_file")
        rows.append(
            {
                "client_id": str(client_id),
                "source_file": None if source_file is None else str(source_file),
            }
        )
    return rows


def _format_age_policy_warning_message(
    *,
    label: str,
    row_count: int,
    min_age_years: int,
    max_age_years: int,
    client_ids: list[str],
    client_id_source_rows: list[dict[str, str | None]],
) -> str:
    header = (
        f"ISPA age policy warning in {label}: "
        f"{row_count} rows outside {min_age_years}-{max_age_years}"
    )

    detail_lines: list[str] = []
    if client_id_source_rows:
        detail_lines = [
            (
                f"    client_id={row['client_id']} "
                f"source_file={row['source_file'] or 'UNKNOWN'}"
            )
            for row in client_id_source_rows
        ]
    elif client_ids:
        detail_lines = [f"    client_id={client_id}" for client_id in client_ids]

    if not detail_lines:
        return header
    return "\n".join([f"{header}:", *detail_lines])


def require_previous_business_day(
    *,
    previous_business_day: date | None,
    run_date: str,
    label: str,
    rule_id: str = RULE_PREVIOUS_BUSINESS_DAY_ID,
) -> date:
    if previous_business_day is not None:
        return previous_business_day
    raise ValidationError(
        f"VALIDATION FAIL [{rule_id}] previous business day is required for {label} but is unavailable "
        f"for run_date={run_date}"
    )


def parse_date_token(value: str, *, field_name: str) -> date:
    raw = str(value).strip()
    if not raw:
        raise ValidationError(f"{field_name} must be a non-empty YYYYMMDD token")
    try:
        return datetime.strptime(raw, _RUN_DATE_FORMAT).date()
    except ValueError as exc:
        raise ValidationError(
            f"{field_name} must use YYYYMMDD format. got={value!r}"
        ) from exc


def require_increasing_date_range(
    *,
    start_date: date,
    end_date: date,
    start_label: str,
    end_label: str,
    context: str,
    rule_id: str = RULE_DATE_RANGE_ID,
) -> None:
    if start_date < end_date:
        return
    raise ValidationError(
        f"VALIDATION FAIL [{rule_id}] invalid date range for {context}: "
        f"{start_label}={start_date.strftime(_RUN_DATE_FORMAT)} must be earlier than "
        f"{end_label}={end_date.strftime(_RUN_DATE_FORMAT)}"
    )


def previous_scope_data_file_warning(
    *,
    previous_date: str,
    scope_label: str,
    output_id: str,
    required_slices: list[str],
    available_slices: list[str],
    download_enabled: bool = True,
    rule_id: str = RULE_PREVIOUS_SCOPE_DATA_ID,
) -> RuleResult | None:
    if not required_slices:
        return None
    available_set = set(available_slices)
    missing = sorted(
        slice_token
        for slice_token in required_slices
        if slice_token not in available_set
    )
    if not missing:
        return None
    local_cache_note = ""
    if not download_enabled:
        local_cache_note = (
            " No-download mode checks only local compliance_history snapshots; "
            "if prior-day files were pruned locally, this can occur even when ADLS has them."
        )
    return RuleResult(
        rule_id=rule_id,
        code="previous_scope_data_files_missing",
        severity="warning",
        message=(
            f"previous business day scope data files are unavailable for {output_id}. "
            f"scope={scope_label} previous_date={previous_date} missing_slices={missing}. "
            "Day-over-business-day outputs may be less accurate."
            f"{local_cache_note}"
        ),
        count=len(missing),
        context={
            "output_id": output_id,
            "scope_label": scope_label,
            "previous_date": previous_date,
            "missing_slices": missing,
        },
    )


def validate_rescind_window_start_bound(
    *,
    frame: pl.DataFrame,
    wave_window_starts: Mapping[str, date],
    label: str,
    rule_id: str = RULE_PEAR_RESCIND_WINDOW_START_ID,
) -> None:
    required_columns = {"client_id", "wave", "rescind_date"}
    missing_columns = sorted(required_columns - set(frame.columns))
    if missing_columns:
        raise ValidationError(
            f"VALIDATION FAIL [{rule_id}] {label} is missing required columns for "
            f"rescind-date validation: {missing_columns}"
        )

    if frame.is_empty():
        return

    rescinded = frame.filter(pl.col("rescind_date").is_not_null())
    if rescinded.is_empty():
        return

    if not wave_window_starts:
        raise ValidationError(
            f"VALIDATION FAIL [{rule_id}] school_reference wave-window metadata is "
            "required for rescind-date validation"
        )

    starts = {
        str(wave).strip().upper(): start for wave, start in wave_window_starts.items()
    }
    starts_frame = pl.DataFrame(
        {
            "wave": list(starts.keys()),
            "_suspension_window_start": list(starts.values()),
        }
    )

    scoped = rescinded.with_columns(
        pl.col("wave")
        .cast(pl.String, strict=False)
        .str.strip_chars()
        .str.to_uppercase()
        .alias("wave")
    ).join(starts_frame, on="wave", how="left")

    missing_wave_rows = scoped.filter(pl.col("_suspension_window_start").is_null())
    if missing_wave_rows.height:
        details = [
            f"    client_id={row['client_id']} wave={row['wave']}"
            for row in missing_wave_rows.select("client_id", "wave")
            .sort(["wave", "client_id"])
            .to_dicts()
        ]
        raise ValidationError(
            f"VALIDATION FAIL [{rule_id}] {label} contains rescinded rows for waves "
            "missing suspension_window_start metadata:\n" + "\n".join(details)
        )

    invalid = scoped.filter(pl.col("rescind_date") < pl.col("_suspension_window_start"))
    if invalid.is_empty():
        return

    details = [
        (
            f"    client_id={row['client_id']} "
            f"wave={row['wave']} "
            f"rescind_date={row['rescind_date']} "
            f"suspension_window_start={row['_suspension_window_start']}"
        )
        for row in invalid.select(
            "client_id",
            "wave",
            "rescind_date",
            "_suspension_window_start",
        )
        .sort(["wave", "client_id"])
        .to_dicts()
    ]
    raise ValidationError(
        f"VALIDATION FAIL [{rule_id}] {label} has rescind_date values before "
        "suspension_window_start:\n" + "\n".join(details)
    )


def _fail_on_invalid_dates(
    *,
    frame: pl.DataFrame,
    condition: pl.Expr,
    label: str,
    code: str,
    detail: str,
) -> None:
    invalid = frame.filter(condition)
    if invalid.is_empty():
        return
    sample_ids = _sample_client_ids(invalid)
    raise ValidationError(
        f"VALIDATION FAIL [{RULE_TEMPORAL_BOUNDS_ID}] {code} in {label}: {detail}. "
        f"rows={invalid.height} sample_client_ids={sample_ids}"
    )


def _age_years_expr(run_day: date) -> pl.Expr:
    return (
        (
            (pl.lit(run_day).cast(pl.Date) - pl.col("date_of_birth")).dt.total_days()
            / 365.25
        )
        .floor()
        .cast(pl.Int64, strict=False)
        .alias("_age_years")
    )


def validate_temporal_bounds(
    *,
    frame: pl.DataFrame,
    run_day: date,
    label: str,
    policy: TemporalPolicy | None = None,
) -> list[RuleResult]:
    if frame.is_empty():
        return []
    policy = policy or TemporalPolicy()

    if "date_of_birth" in frame.columns:
        _fail_on_invalid_dates(
            frame=frame,
            condition=pl.col("date_of_birth").is_not_null()
            & (pl.col("date_of_birth") < pl.lit(_MIN_VALID_DATE)),
            label=label,
            code="dob_before_min",
            detail=f"date_of_birth cannot be earlier than {_MIN_VALID_DATE.isoformat()}",
        )
        _fail_on_invalid_dates(
            frame=frame,
            condition=pl.col("date_of_birth").is_not_null()
            & (pl.col("date_of_birth") > pl.lit(run_day)),
            label=label,
            code="dob_after_run_day",
            detail=f"date_of_birth cannot be later than run_day={run_day.isoformat()}",
        )

    if "compliant" in frame.columns:
        _fail_on_invalid_dates(
            frame=frame,
            condition=pl.col("compliant").is_not_null()
            & (pl.col("compliant") < pl.lit(_MIN_VALID_DATE)),
            label=label,
            code="compliant_before_min",
            detail=f"compliant cannot be earlier than {_MIN_VALID_DATE.isoformat()}",
        )
        _fail_on_invalid_dates(
            frame=frame,
            condition=pl.col("compliant").is_not_null()
            & (pl.col("compliant") > pl.lit(run_day)),
            label=label,
            code="compliant_after_run_day",
            detail=f"compliant cannot be later than run_day={run_day.isoformat()}",
        )

    if {"date_of_birth", "compliant"}.issubset(set(frame.columns)):
        _fail_on_invalid_dates(
            frame=frame,
            condition=pl.col("compliant").is_not_null()
            & pl.col("date_of_birth").is_not_null()
            & (pl.col("compliant") < pl.col("date_of_birth")),
            label=label,
            code="compliant_before_dob",
            detail="compliant cannot be earlier than date_of_birth",
        )

    warnings: list[RuleResult] = []
    if "date_of_birth" in frame.columns:
        aged = frame.with_columns(_age_years_expr(run_day))
        age_policy_scope = pl.col("date_of_birth").is_not_null()
        if "compliant" in aged.columns:
            # Only warn for unresolved records; historical compliant rows should not alert.
            age_policy_scope = age_policy_scope & pl.col("compliant").is_null()
        outside_age = aged.filter(
            age_policy_scope
            & (
                (pl.col("_age_years") < policy.min_age_years)
                | (pl.col("_age_years") > policy.max_age_years)
            )
        )
        if outside_age.height:
            client_ids = _all_client_ids(outside_age)
            source_files = _all_source_files(outside_age)
            client_id_source_rows = _client_id_source_rows(outside_age)
            warnings.append(
                RuleResult(
                    rule_id=RULE_TEMPORAL_BOUNDS_ID,
                    code="age_out_of_policy",
                    severity="warning",
                    message=_format_age_policy_warning_message(
                        label=label,
                        row_count=int(outside_age.height),
                        min_age_years=policy.min_age_years,
                        max_age_years=policy.max_age_years,
                        client_ids=client_ids,
                        client_id_source_rows=client_id_source_rows,
                    ),
                    count=int(outside_age.height),
                    context={
                        "label": label,
                        "min_age_years": policy.min_age_years,
                        "max_age_years": policy.max_age_years,
                        "client_ids": client_ids,
                        "source_files": source_files,
                        "client_id_to_source_file": client_id_source_rows,
                        "sample_client_ids": _sample_client_ids(outside_age),
                    },
                )
            )

    return warnings
