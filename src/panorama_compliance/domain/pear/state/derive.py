from __future__ import annotations

from datetime import date
from pathlib import Path

import polars as pl

from panorama_compliance.domain.pear.state._common import (
    _INPUT_SCHEMA_BY_STATE,
    REPORT_OVERDUE,
    REPORT_SUSPENSION,
    REPORT_SUSPENSION_OPERATIONAL,
    REPORT_SUSPENSION_VS_OVERDUE,
)
from panorama_compliance.domain.pear.state.continuity import (
    _build_suspension_continuity_plan,
)
from panorama_compliance.domain.pear.state.output import (
    discover_latest_pear_authoritative_baseline_by_slice,
)
from panorama_compliance.domain.pear.state.reconcile import (
    _attach_scope_columns,
    _build_overdue_day_over_day_warnings,
    _derive_operational_suspension_state,
    _patch_suspension_rescinds_from_action_queue,
    _read_authoritative_baseline_state,
    _read_processed_frame,
    _read_suspension_state,
    _project_state_columns,
    _reconcile_suspension_disappearances,
    _validate_action_domain,
)
from panorama_compliance.domain.pear.state.selection import PearProcessedSelection
from panorama_compliance.domain.pear.state.types import PearStateDerivationResult
from panorama_compliance.ingest.combine import wave_to_token
from panorama_compliance.domain.common.workdays import WorkdayInfo
from panorama_compliance.reference import SchoolReference
from panorama_compliance.schema import validate_unique_key
from panorama_compliance.validation.catalog import (
    RULE_PEAR_OVERDUE_DAY_OVER_DAY_ID,
    RULE_PEAR_RESCIND_WINDOW_START_ID,
)
from panorama_compliance.validation.temporal import validate_rescind_window_start_bound


def derive_pear_state(
    *,
    selection: PearProcessedSelection,
    schema_root: Path,
    reference: SchoolReference,
    authoritative_dir: Path | None = None,
    workdays: dict[date, WorkdayInfo] | None = None,
    continuity_waived_waves: set[str] | None = None,
    strict_headers: bool = True,
) -> PearStateDerivationResult:
    warning_messages: list[str] = []
    continuity_warning_messages: tuple[str, ...] = ()
    overdue_day_over_day_warning_messages: tuple[str, ...] = ()
    disappearance_warning_messages: tuple[str, ...] = ()
    overdue_day_over_day_summary: dict[str, object] = {
        "rule_id": RULE_PEAR_OVERDUE_DAY_OVER_DAY_ID,
        "status": "not_evaluated",
        "run_date": selection.run_date,
        "current_overdue_date": selection.selected_dates.get(REPORT_OVERDUE),
        "previous_business_day": None,
        "previous_overdue_file": None,
        "current_overdue_count": 0,
        "introduced_client_count": 0,
    }
    prior_suspension_paths = selection.previous_suspension_paths
    previous_suspension_date = selection.previous_suspension_date
    prior_suspension_source = "none"
    prior_source_paths: tuple[Path, ...] = ()
    compare_waves: set[str] | None = None
    baseline_dir = authoritative_dir
    if workdays is not None:
        continuity_plan = _build_suspension_continuity_plan(
            selection=selection,
            reference=reference,
            workdays=workdays,
            continuity_waived_waves=continuity_waived_waves,
        )
        prior_suspension_paths = continuity_plan.prior_suspension_paths
        previous_suspension_date = continuity_plan.previous_suspension_date
        compare_waves = set(continuity_plan.comparison_waves)
        continuity_warning_messages = continuity_plan.warning_messages
        warning_messages.extend(continuity_warning_messages)

    suspension_state_current = _read_suspension_state(
        suspension_paths=selection.suspension_paths,
        schema_root=schema_root,
        reference=reference,
        label="suspension_active",
        strict_headers=strict_headers,
    )

    prior_suspension_state: pl.DataFrame | None = None
    if previous_suspension_date and baseline_dir is not None:
        available_prior_baseline = discover_latest_pear_authoritative_baseline_by_slice(
            baseline_dir,
            run_date=previous_suspension_date,
            exact_run_date=True,
        )
        expected_tokens: set[str] | None = None
        if compare_waves:
            expected_tokens = {wave_to_token(wave) for wave in compare_waves}
        selected_prior_baseline = {
            slice_token: path
            for slice_token, path in available_prior_baseline.items()
            if expected_tokens is None or slice_token in expected_tokens
        }
        missing_tokens = sorted(
            (expected_tokens or set()) - set(selected_prior_baseline)
        )
        if missing_tokens:
            warning_messages.append(
                "PEAR suspension continuity warning: previous official "
                "suspension-operational baseline "
                f"for {previous_suspension_date} is missing slices "
                f"{', '.join(missing_tokens)}; falling back to processed prior "
                "suspension lists."
            )
        elif selected_prior_baseline:
            prior_source_paths = tuple(
                path for _, path in sorted(selected_prior_baseline.items())
            )
            prior_suspension_state = _read_authoritative_baseline_state(
                authoritative_paths=prior_source_paths,
                reference=reference,
                label="prior suspension_operational",
            )
            prior_suspension_source = "official_operational_baseline"

    if prior_suspension_state is None and prior_suspension_paths:
        prior_suspension_state = _read_suspension_state(
            suspension_paths=prior_suspension_paths,
            schema_root=schema_root,
            reference=reference,
            label="prior suspension_active",
            strict_headers=strict_headers,
        )
        prior_suspension_source = "processed_prior_suspension"

    overdue_frames = [
        _read_processed_frame(
            path=path,
            schema_root=schema_root,
            dataset_id=_INPUT_SCHEMA_BY_STATE[REPORT_OVERDUE],
            label=path.name,
            strict_headers=strict_headers,
        )
        for path in selection.overdue_paths
    ]
    overdue_df = pl.concat(overdue_frames, how="vertical")
    validate_unique_key(
        overdue_df, key="client_id", label="overdue_active combined source"
    )
    overdue_df = _attach_scope_columns(
        overdue_df, reference=reference, label="overdue_active source"
    )
    overdue_state = _project_state_columns(overdue_df, state_name=REPORT_OVERDUE)
    overdue_day_over_day_summary["current_overdue_count"] = int(overdue_state.height)

    if workdays is not None:
        (
            overdue_day_over_day_summary,
            overdue_day_over_day_warning_messages,
        ) = _build_overdue_day_over_day_warnings(
            selection=selection,
            overdue_state=overdue_state,
            schema_root=schema_root,
            reference=reference,
            workdays=workdays,
            strict_headers=strict_headers,
        )
        warning_messages.extend(overdue_day_over_day_warning_messages)

    action_frames = [
        _read_processed_frame(
            path=path,
            schema_root=schema_root,
            dataset_id=_INPUT_SCHEMA_BY_STATE[REPORT_SUSPENSION_VS_OVERDUE],
            label=path.name,
            strict_headers=strict_headers,
        )
        for path in selection.suspension_vs_overdue_paths
    ]
    action_df = pl.concat(action_frames, how="vertical")
    validate_unique_key(
        action_df,
        key="client_id",
        label="suspension_vs_overdue combined source",
    )
    _validate_action_domain(
        action_df,
        label="suspension_vs_overdue combined source",
    )
    action_df = _attach_scope_columns(
        action_df, reference=reference, label="suspension_vs_overdue source"
    )
    action_state = _project_state_columns(
        action_df, state_name=REPORT_SUSPENSION_VS_OVERDUE
    )
    (
        suspension_state_current,
        rescind_patch_summary,
    ) = _patch_suspension_rescinds_from_action_queue(
        suspension_state=suspension_state_current,
        action_state=action_state,
    )
    (
        suspension_state,
        disappearance_evidence,
        disappearance_summary,
        disappearance_warning_messages,
    ) = _reconcile_suspension_disappearances(
        current_suspension_state=suspension_state_current,
        prior_suspension_state=prior_suspension_state,
        action_state=action_state,
        current_suspension_date=selection.selected_dates[REPORT_SUSPENSION],
        previous_suspension_date=previous_suspension_date,
        compare_waves=compare_waves,
    )
    warning_messages.extend(disappearance_warning_messages)
    validate_rescind_window_start_bound(
        frame=suspension_state,
        wave_window_starts={
            wave: window.suspension_window_start
            for wave, window in reference.wave_windows.items()
        },
        label="suspension_active",
        rule_id=RULE_PEAR_RESCIND_WINDOW_START_ID,
    )
    suspension_operational = _derive_operational_suspension_state(
        suspension_state=suspension_state,
        action_state=action_state,
    )

    return PearStateDerivationResult(
        selection=selection,
        frames={
            REPORT_SUSPENSION: suspension_state,
            REPORT_OVERDUE: overdue_state,
            REPORT_SUSPENSION_VS_OVERDUE: action_state,
            REPORT_SUSPENSION_OPERATIONAL: suspension_operational,
        },
        disappearance_evidence=disappearance_evidence,
        disappearance_summary=disappearance_summary,
        rescind_patch_summary=rescind_patch_summary,
        overdue_day_over_day_summary=overdue_day_over_day_summary,
        prior_suspension_source=prior_suspension_source,
        critical_messages=(),
        continuity_warning_messages=continuity_warning_messages,
        overdue_day_over_day_warning_messages=overdue_day_over_day_warning_messages,
        disappearance_warning_messages=disappearance_warning_messages,
        warning_messages=tuple(warning_messages),
    )


from panorama_compliance.domain.pear.state.output import (
    discover_latest_pear_state_by_slice,
    write_pear_authoritative_suspension_outputs,
    write_pear_state_outputs,
)

__all__ = [
    "PearStateDerivationResult",
    "derive_pear_state",
    "discover_latest_pear_authoritative_baseline_by_slice",
    "discover_latest_pear_state_by_slice",
    "write_pear_authoritative_suspension_outputs",
    "write_pear_state_outputs",
]
