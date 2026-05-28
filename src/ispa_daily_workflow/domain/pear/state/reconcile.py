from __future__ import annotations

from datetime import date
from pathlib import Path

import polars as pl

from ispa_daily_workflow.domain.common.workdays import WorkdayInfo
from ispa_daily_workflow.domain.pear.state._common import (
    _ACTION_REQUIRED_VALUES,
    _DISAPPEARANCE_EVIDENCE_COLUMNS,
    _INPUT_SCHEMA_BY_STATE,
    _STATE_COLUMNS,
    REPORT_OVERDUE,
    REPORT_SUSPENSION,
    REPORT_SUSPENSION_OPERATIONAL,
    RescindPatchSummary,
    _format_date_token,
    _parse_date_token,
)
from ispa_daily_workflow.domain.pear.state.selection import (
    PearProcessedSelection,
    _select_overdue_paths_for_date,
)
from ispa_daily_workflow.reference import SchoolReference
from ispa_daily_workflow.schema import (
    ValidationError,
    apply_schema_types,
    resolve_dataset_schema,
    validate_exact_headers,
    validate_required_non_null,
    validate_unique_key,
)
from ispa_daily_workflow.validation.catalog import RULE_PEAR_OVERDUE_DAY_OVER_DAY_ID


def _build_overdue_day_over_day_warnings(
    *,
    selection: PearProcessedSelection,
    overdue_state: pl.DataFrame,
    schema_root: Path,
    reference: SchoolReference,
    workdays: dict[date, WorkdayInfo],
    strict_headers: bool = True,
) -> tuple[dict[str, object], tuple[str, ...]]:
    summary: dict[str, object] = {
        "rule_id": RULE_PEAR_OVERDUE_DAY_OVER_DAY_ID,
        "status": "not_evaluated",
        "run_date": selection.run_date,
        "current_overdue_date": selection.selected_dates.get(REPORT_OVERDUE),
        "previous_business_day": None,
        "previous_overdue_file": None,
        "current_overdue_count": int(overdue_state.height),
        "introduced_client_count": 0,
    }

    run_day = _parse_date_token(selection.run_date, label="run_date")
    run_info = workdays.get(run_day)
    if run_info is None:
        summary["status"] = "warning"
        warning = (
            "PEAR overdue day-over-day check skipped: "
            f"run_date={selection.run_date} is missing from run.workdays_csv"
        )
        return summary, (warning,)

    previous_business_day = run_info.previous_business_day
    if previous_business_day is None:
        summary["status"] = "warning"
        warning = (
            "PEAR overdue day-over-day check skipped: "
            f"run_date={selection.run_date} has no previous business day in run.workdays_csv"
        )
        return summary, (warning,)

    previous_token = _format_date_token(previous_business_day)
    summary["previous_business_day"] = previous_token
    current_overdue_date = str(selection.selected_dates.get(REPORT_OVERDUE) or "")
    if current_overdue_date != selection.run_date:
        summary["status"] = "warning"
        warning = (
            "PEAR overdue day-over-day check skipped: "
            f"run_date={selection.run_date} overdue report is unavailable "
            f"(selected_overdue_date={current_overdue_date})"
        )
        return summary, (warning,)

    previous_overdue_paths = _select_overdue_paths_for_date(
        processed_dir=selection.overdue_path.parent,
        date_token=previous_token,
    )
    summary["previous_overdue_file"] = ", ".join(
        path.name for path in previous_overdue_paths
    )
    if not previous_overdue_paths:
        summary["status"] = "warning"
        warning = (
            "PEAR overdue day-over-day check skipped: "
            f"previous business day overdue file is unavailable "
            f"({previous_token}_overdue_list_pear.parquet)"
        )
        return summary, (warning,)

    previous_overdue_frames = [
        _read_processed_frame(
            path=path,
            schema_root=schema_root,
            dataset_id=_INPUT_SCHEMA_BY_STATE[REPORT_OVERDUE],
            label=path.name,
            strict_headers=strict_headers,
        )
        for path in previous_overdue_paths
    ]
    previous_overdue_df = pl.concat(previous_overdue_frames, how="vertical")
    validate_unique_key(
        previous_overdue_df,
        key="client_id",
        label=f"overdue prior source {previous_token}",
    )
    previous_overdue_df = _attach_scope_columns(
        previous_overdue_df,
        reference=reference,
        label="prior overdue_active source",
    )
    previous_overdue_state = _project_state_columns(
        previous_overdue_df,
        state_name=REPORT_OVERDUE,
    )

    introduced = (
        overdue_state.select("client_id", "school_id", "wave")
        .join(
            previous_overdue_state.select("client_id"),
            on="client_id",
            how="anti",
        )
        .sort(["wave", "school_id", "client_id"])
    )
    introduced_count = int(introduced.height)
    summary["introduced_client_count"] = introduced_count
    if introduced_count == 0:
        summary["status"] = "pass"
        return summary, ()

    detail_lines = [
        (
            f"    client_id={row['client_id']} "
            f"school_id={row['school_id']} "
            f"wave={row['wave']}"
        )
        for row in introduced.to_dicts()
    ]
    header = (
        "PEAR overdue day-over-day warning: "
        f"{introduced_count} current overdue rows are absent from previous business day "
        f"overdue list (run_date={selection.run_date} previous_business_day={previous_token})"
    )
    summary["status"] = "warning"
    return summary, ("\n".join([header + ":", *detail_lines]),)


def _validate_client_id_column(frame: pl.DataFrame, *, label: str) -> None:
    invalid = frame.filter(
        pl.col("client_id")
        .cast(pl.String, strict=False)
        .str.strip_chars()
        .str.contains(r"^[0-9]{10}$")
        .not_()
    )
    if invalid.height:
        raise ValidationError(
            f"{label}: {invalid.height} rows failed client_id 10-digit validation"
        )


def _read_processed_frame(
    *,
    path: Path,
    schema_root: Path,
    dataset_id: str,
    label: str,
    strict_headers: bool = True,
) -> pl.DataFrame:
    schema = resolve_dataset_schema(dataset_id, schema_root=schema_root)
    frame = pl.read_parquet(path)
    if strict_headers:
        validate_exact_headers(list(frame.columns), schema, label)
    typed = apply_schema_types(frame, schema)
    validate_required_non_null(typed, schema, label)
    validate_unique_key(typed, key="client_id", label=label)
    _validate_client_id_column(typed, label=label)
    return typed


def _reference_scope_frame(reference: SchoolReference) -> pl.DataFrame:
    rows = [
        [school_id, record.level, record.wave]
        for school_id, record in sorted(reference.by_id.items())
    ]
    return pl.DataFrame(
        rows,
        schema=["school_id", "level", "wave"],
        orient="row",
    )


def _attach_scope_columns(
    frame: pl.DataFrame,
    *,
    reference: SchoolReference,
    label: str,
) -> pl.DataFrame:
    normalized = frame.with_columns(
        pl.col("school_id")
        .cast(pl.String, strict=False)
        .str.strip_chars()
        .alias("school_id")
    )
    scope_frame = _reference_scope_frame(reference)
    enriched = normalized.join(scope_frame, on="school_id", how="left")

    unresolved = (
        enriched.filter(pl.col("wave").is_null() | pl.col("level").is_null())
        .select("school_id")
        .unique()
        .sort("school_id")
    )
    if unresolved.height:
        unresolved_ids = ", ".join(unresolved.get_column("school_id").to_list())
        raise ValidationError(
            f"{label}: school_id values missing from school reference: {unresolved_ids}"
        )
    return enriched


def _project_state_columns(frame: pl.DataFrame, *, state_name: str) -> pl.DataFrame:
    columns = _STATE_COLUMNS[state_name]
    output = frame
    for column in columns:
        if column not in output.columns:
            output = output.with_columns(pl.lit(None).alias(column))
    projected = output.select(columns)
    validate_unique_key(projected, key="client_id", label=f"{state_name} state")
    return projected


def _validate_action_domain(frame: pl.DataFrame, *, label: str) -> None:
    invalid = frame.filter(
        ~pl.col("action_required").is_in(sorted(_ACTION_REQUIRED_VALUES))
    )
    if invalid.height:
        seen_values = (
            invalid.select("action_required")
            .unique()
            .get_column("action_required")
            .to_list()
        )
        raise ValidationError(
            f"{label}: invalid action_required values {sorted(seen_values)}; "
            f"expected {sorted(_ACTION_REQUIRED_VALUES)}"
        )


def _empty_disappearance_evidence() -> pl.DataFrame:
    return pl.DataFrame(
        schema={
            "client_id": pl.Utf8,
            "school_id": pl.Utf8,
            "school_name": pl.Utf8,
            "first_name": pl.Utf8,
            "last_name": pl.Utf8,
            "date_of_birth": pl.Date,
            "rescind_date": pl.Date,
            "level": pl.Utf8,
            "wave": pl.Utf8,
            "action_required": pl.Utf8,
            "action_date": pl.Date,
            "mapped_action": pl.Utf8,
            "mapped_action_date": pl.Date,
            "evidence_source": pl.Utf8,
            "resolution_status": pl.Utf8,
            "current_suspension_date": pl.Utf8,
            "previous_suspension_date": pl.Utf8,
        }
    )


def _read_suspension_state(
    *,
    suspension_paths: tuple[Path, ...],
    schema_root: Path,
    reference: SchoolReference,
    label: str,
    strict_headers: bool = True,
) -> pl.DataFrame:
    suspension_frames = [
        _read_processed_frame(
            path=path,
            schema_root=schema_root,
            dataset_id=_INPUT_SCHEMA_BY_STATE[REPORT_SUSPENSION],
            label=path.name,
            strict_headers=strict_headers,
        )
        for path in suspension_paths
    ]
    suspension_df = pl.concat(suspension_frames, how="vertical")
    validate_unique_key(
        suspension_df, key="client_id", label=f"{label} combined source"
    )
    suspension_df = _attach_scope_columns(
        suspension_df, reference=reference, label=f"{label} source"
    )
    return _project_state_columns(suspension_df, state_name=REPORT_SUSPENSION)


def _derive_operational_suspension_state(
    *,
    suspension_state: pl.DataFrame,
    action_state: pl.DataFrame,
) -> pl.DataFrame:
    if suspension_state.is_empty():
        return _project_state_columns(
            suspension_state, state_name=REPORT_SUSPENSION_OPERATIONAL
        )

    # Keep rescind rows in suspension_operational for report visibility. Delete
    # actions only suppress rows that are still active (rescind_date is null).
    delete_flags = (
        action_state.filter(pl.col("action_required") == "delete")
        .select("client_id")
        .unique(subset=["client_id"], keep="first", maintain_order=True)
        .with_columns(pl.lit(True).alias("_matched_delete"))
    )
    joined = suspension_state.join(delete_flags, on="client_id", how="left")
    operational = joined.filter(
        ~(pl.col("_matched_delete").fill_null(False) & pl.col("rescind_date").is_null())
    ).drop("_matched_delete")
    return _project_state_columns(operational, state_name=REPORT_SUSPENSION_OPERATIONAL)


def _read_authoritative_baseline_state(
    *,
    authoritative_paths: tuple[Path, ...],
    reference: SchoolReference,
    label: str,
) -> pl.DataFrame:
    baseline_frames = [
        _project_state_columns(
            pl.read_parquet(path),
            state_name=REPORT_SUSPENSION_OPERATIONAL,
        )
        for path in authoritative_paths
    ]
    baseline_df = pl.concat(baseline_frames, how="vertical")
    validate_unique_key(
        baseline_df,
        key="client_id",
        label=f"{label} combined source",
    )
    # Re-derive scope from school reference to keep continuity checks aligned
    # with current identifier authority.
    drop_scope_columns = [
        name for name in ("level", "wave") if name in baseline_df.columns
    ]
    if drop_scope_columns:
        baseline_df = baseline_df.drop(drop_scope_columns)
    baseline_df = _attach_scope_columns(
        baseline_df,
        reference=reference,
        label=f"{label} source",
    )
    return _project_state_columns(baseline_df, state_name=REPORT_SUSPENSION_OPERATIONAL)


def _patch_suspension_rescinds_from_action_queue(
    *,
    suspension_state: pl.DataFrame,
    action_state: pl.DataFrame,
) -> tuple[pl.DataFrame, RescindPatchSummary]:
    suspension_ids = suspension_state.select("client_id").unique()
    delete_actions = (
        action_state.filter(pl.col("action_required") == "delete")
        .select("client_id")
        .unique(subset=["client_id"], keep="first", maintain_order=True)
    )
    delete_action_rows = int(delete_actions.height)
    matched_delete_client_ids = (
        suspension_ids.join(delete_actions, on="client_id", how="inner")
        .sort("client_id")
        .get_column("client_id")
        .to_list()
    )
    matched_delete_client_ids = [str(value) for value in matched_delete_client_ids]
    matched_delete_rows = len(matched_delete_client_ids)

    rescind_actions = (
        action_state.filter(pl.col("action_required") == "rescind")
        .select(
            "client_id",
            pl.col("action_date")
            .cast(pl.Date, strict=False)
            .alias("rescind_action_date"),
        )
        .unique(subset=["client_id"], keep="first", maintain_order=True)
    )
    if rescind_actions.is_empty():
        return (
            suspension_state,
            {
                "rescind_action_rows": 0,
                "matched_rescind_rows": 0,
                "patched_rescind_rows": 0,
                "preserved_existing_rescind_rows": 0,
                "unmatched_rescind_action_rows": 0,
                "delete_action_rows": delete_action_rows,
                "matched_delete_rows": matched_delete_rows,
                "unmatched_delete_action_rows": delete_action_rows
                - matched_delete_rows,
                "matched_delete_client_ids": matched_delete_client_ids,
            },
        )

    joined = suspension_state.join(rescind_actions, on="client_id", how="left")
    patched = joined.with_columns(
        (
            pl.col("rescind_date").is_null()
            & pl.col("rescind_action_date").is_not_null()
        ).alias("_patched_from_action"),
        pl.when(
            pl.col("rescind_date").is_null()
            & pl.col("rescind_action_date").is_not_null()
        )
        .then(pl.col("rescind_action_date"))
        .otherwise(pl.col("rescind_date"))
        .cast(pl.Date, strict=False)
        .alias("rescind_date"),
    ).drop("rescind_action_date")
    matched_rescind_rows = int(
        joined.filter(pl.col("rescind_action_date").is_not_null()).height
    )
    patched_rescind_rows = int(patched.filter(pl.col("_patched_from_action")).height)
    patched = patched.drop("_patched_from_action")

    rescind_action_rows = int(rescind_actions.height)
    summary = {
        "rescind_action_rows": rescind_action_rows,
        "matched_rescind_rows": matched_rescind_rows,
        "patched_rescind_rows": patched_rescind_rows,
        "preserved_existing_rescind_rows": matched_rescind_rows - patched_rescind_rows,
        "unmatched_rescind_action_rows": rescind_action_rows - matched_rescind_rows,
        "delete_action_rows": delete_action_rows,
        "matched_delete_rows": matched_delete_rows,
        "unmatched_delete_action_rows": delete_action_rows - matched_delete_rows,
        "matched_delete_client_ids": matched_delete_client_ids,
    }
    return patched, summary


def _reconcile_suspension_disappearances(
    *,
    current_suspension_state: pl.DataFrame,
    prior_suspension_state: pl.DataFrame | None,
    action_state: pl.DataFrame,
    current_suspension_date: str,
    previous_suspension_date: str | None,
    compare_waves: set[str] | None = None,
) -> tuple[pl.DataFrame, pl.DataFrame, dict[str, int], tuple[str, ...]]:
    comparison_current = current_suspension_state
    comparison_prior = prior_suspension_state
    passthrough_state = current_suspension_state.filter(pl.lit(False))
    if compare_waves is not None:
        if not compare_waves:
            return (
                current_suspension_state,
                _empty_disappearance_evidence(),
                {
                    "prior_suspension_count": 0,
                    "current_suspension_count": current_suspension_state.height,
                    "disappeared_count": 0,
                    "resolved_count": 0,
                    "unresolved_count": 0,
                    "rehydrated_count": 0,
                },
                (),
            )
        compare_values = sorted(compare_waves)
        comparison_current = current_suspension_state.filter(
            pl.col("wave").is_in(compare_values)
        )
        passthrough_state = current_suspension_state.filter(
            ~pl.col("wave").is_in(compare_values)
        )
        if comparison_prior is not None:
            comparison_prior = comparison_prior.filter(
                pl.col("wave").is_in(compare_values)
            )

    def _combine_with_passthrough(scoped_state: pl.DataFrame) -> pl.DataFrame:
        if passthrough_state.is_empty():
            combined = scoped_state
        elif scoped_state.is_empty():
            combined = passthrough_state
        else:
            combined = pl.concat([scoped_state, passthrough_state], how="vertical")
        validate_unique_key(
            combined,
            key="client_id",
            label="suspension_active reconciled state",
        )
        return combined

    if comparison_prior is None or comparison_prior.is_empty():
        return (
            _combine_with_passthrough(comparison_current),
            _empty_disappearance_evidence(),
            {
                "prior_suspension_count": 0,
                "current_suspension_count": comparison_current.height,
                "disappeared_count": 0,
                "resolved_count": 0,
                "unresolved_count": 0,
                "rehydrated_count": 0,
            },
            (),
        )

    disappeared = comparison_prior.join(
        comparison_current.select("client_id"),
        on="client_id",
        how="anti",
    )
    if disappeared.is_empty():
        return (
            _combine_with_passthrough(comparison_current),
            _empty_disappearance_evidence(),
            {
                "prior_suspension_count": comparison_prior.height,
                "current_suspension_count": comparison_current.height,
                "disappeared_count": 0,
                "resolved_count": 0,
                "unresolved_count": 0,
                "rehydrated_count": 0,
            },
            (),
        )

    action_lookup = action_state.select("client_id", "action_required", "action_date")
    dropoff_date = _parse_date_token(
        current_suspension_date,
        label="current_suspension_date",
    )
    disappearance_evidence = (
        disappeared.join(action_lookup, on="client_id", how="left")
        .with_columns(
            pl.col("rescind_date")
            .cast(pl.Date, strict=False)
            .alias("prior_rescind_date")
        )
        .with_columns(
            pl.when(pl.col("action_required") == "rescind")
            .then(pl.lit("rescind"))
            .when(pl.col("prior_rescind_date").is_not_null())
            .then(pl.lit("rescind"))
            .when(pl.col("action_required") == "delete")
            .then(pl.lit("delete"))
            .otherwise(pl.lit(None))
            .alias("mapped_action"),
            pl.when(pl.col("action_required") == "rescind")
            .then(pl.col("action_date"))
            .when(pl.col("prior_rescind_date").is_not_null())
            .then(pl.col("prior_rescind_date"))
            .otherwise(pl.lit(None))
            .cast(pl.Date)
            .alias("mapped_action_date"),
        )
        .with_columns(
            pl.when(pl.col("prior_rescind_date").is_not_null())
            .then(pl.col("prior_rescind_date"))
            .when(pl.col("action_required") == "rescind")
            .then(pl.col("action_date"))
            .otherwise(pl.lit(dropoff_date))
            .cast(pl.Date)
            .alias("rescind_date"),
            pl.when(pl.col("action_required") == "rescind")
            .then(pl.lit("suspension_vs_overdue_rescind"))
            .when(pl.col("prior_rescind_date").is_not_null())
            .then(pl.lit("prior_suspension_rescind_date"))
            .when(pl.col("action_required") == "delete")
            .then(pl.lit("suspension_vs_overdue_delete_without_rescind"))
            .otherwise(pl.lit("missing"))
            .alias("evidence_source"),
            pl.when(pl.col("prior_rescind_date").is_not_null())
            .then(pl.lit("restored_prior_rescind_date"))
            .when(pl.col("action_required") == "rescind")
            .then(pl.lit("restored_action_rescind"))
            .when(pl.col("action_required") == "delete")
            .then(pl.lit("restored_assumed_dropoff_rescind_after_delete"))
            .otherwise(pl.lit("restored_assumed_dropoff_rescind_missing_evidence"))
            .alias("resolution_status"),
            pl.lit(current_suspension_date).alias("current_suspension_date"),
            pl.lit(previous_suspension_date).alias("previous_suspension_date"),
        )
        .select(_DISAPPEARANCE_EVIDENCE_COLUMNS)
        .sort(["wave", "school_id", "client_id"])
    )
    unresolved = disappearance_evidence.filter(
        pl.col("resolution_status").str.starts_with("restored_assumed_dropoff_rescind")
    )
    resolved = disappearance_evidence.filter(
        pl.col("resolution_status").is_in(
            {"restored_prior_rescind_date", "restored_action_rescind"}
        )
    )
    resolved_count = resolved.height

    rehydrated_state = disappearance_evidence.select(_STATE_COLUMNS[REPORT_SUSPENSION])
    reconciled_comparison_state = comparison_current
    if not rehydrated_state.is_empty():
        reconciled_comparison_state = pl.concat(
            [comparison_current, rehydrated_state], how="vertical"
        )
    reconciled_suspension_state = _combine_with_passthrough(reconciled_comparison_state)

    warning_messages = tuple(
        (
            f"client_id={row['client_id']} "
            f"school_id={row['school_id']} "
            f"wave={row['wave']} "
            f"resolution_status={row['resolution_status']} "
            f"restored_rescind_date={row['rescind_date']} "
            f"evidence_source={row['evidence_source']} "
            f"previous_suspension_date={row['previous_suspension_date']}"
        )
        for row in disappearance_evidence.select(
            "client_id",
            "school_id",
            "wave",
            "resolution_status",
            "rescind_date",
            "evidence_source",
            "previous_suspension_date",
        ).to_dicts()
    )
    summary = {
        "prior_suspension_count": comparison_prior.height,
        "current_suspension_count": comparison_current.height,
        "disappeared_count": disappearance_evidence.height,
        "resolved_count": resolved_count,
        "unresolved_count": unresolved.height,
        "rehydrated_count": rehydrated_state.height,
    }
    return (
        reconciled_suspension_state,
        disappearance_evidence,
        summary,
        warning_messages,
    )


__all__ = []
