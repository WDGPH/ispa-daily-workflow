from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import date
from pathlib import Path

import polars as pl

from ispa_daily_workflow.compliance_history import (
    derive_active_noncompliant,
    discover_compliance_history_by_slice_for_date,
)
from ispa_daily_workflow.config import ensure_dir
from ispa_daily_workflow.domain.delivery.pear_state import (
    empty_action_queue_frames_for_scope,
    is_empty_processed_action_queue_snapshot,
    load_scoped_pear_state_frames,
)
from ispa_daily_workflow.domain.delivery.routing import (
    DeliveryScope,
    ensure_scope_non_empty,
)
from ispa_daily_workflow.domain.derivations.diff import derive_daily_diff_frame
from ispa_daily_workflow.io.adapters import OutputPublisher, StateStore
from ispa_daily_workflow.pipeline.delivery_runtime import IOMode
from ispa_daily_workflow.reference import SchoolReference
from ispa_daily_workflow.schema import ValidationError
from ispa_daily_workflow.validation import (
    RULE_PREVIOUS_BUSINESS_DAY_ID,
    RULE_PREVIOUS_SCOPE_DATA_ID,
    RuleResult,
    ValidationSummary,
    previous_scope_data_file_warning,
    project_delivery_contract,
    require_previous_business_day,
)


def non_empty_scope_slices(frames_by_slice: dict[str, pl.DataFrame]) -> list[str]:
    return sorted(
        slice_token
        for slice_token, frame in frames_by_slice.items()
        if frame.height > 0
    )


def available_previous_slices(
    *,
    read_authoritative: bool,
    compliance_history_dir: Path,
    state_store: StateStore | None,
    previous_date: str,
) -> list[str]:
    if not read_authoritative:
        previous_by_slice = discover_compliance_history_by_slice_for_date(
            compliance_history_dir,
            run_date=previous_date,
        )
        return sorted(previous_by_slice.keys())
    if state_store is None:
        raise RuntimeError("Authoritative read mode requires a state store.")
    return state_store.discover_compliance_history_slices_for_date(
        run_date=previous_date,
    )


def write_panorama_diff_xlsx_outputs(
    *,
    snapshot_by_slice: dict[str, pl.DataFrame],
    active_by_slice: dict[str, pl.DataFrame],
    previous_day: date | None,
    run_date: str,
    output_id: str,
    scope: DeliveryScope,
    schema_root: Path,
    diff_dir: Path,
    io_mode: IOMode,
    read_authoritative: bool,
    compliance_history_dir: Path,
    state_store: StateStore | None,
    output_publisher: OutputPublisher | None,
    validation_summary: ValidationSummary,
    warning_recorder: Callable[[RuleResult], None],
    pass_log: Callable[..., None],
) -> tuple[list[Path], int]:
    try:
        required_previous_day = require_previous_business_day(
            previous_business_day=previous_day,
            run_date=run_date,
            label=output_id,
        )
    except ValidationError as exc:
        validation_summary.record_failure(
            rule_id=RULE_PREVIOUS_BUSINESS_DAY_ID,
            message=str(exc),
            log=logging.error,
        )
        raise
    validation_summary.record_pass(
        rule_id=RULE_PREVIOUS_BUSINESS_DAY_ID,
        message=f"previous business day resolved for {output_id}",
        log=pass_log,
    )
    ensure_scope_non_empty(
        frames_by_slice=active_by_slice,
        scope=scope,
        label="daily diff current active rows",
    )
    previous_date = required_previous_day.strftime("%Y%m%d")
    available_slices = available_previous_slices(
        read_authoritative=read_authoritative,
        compliance_history_dir=compliance_history_dir,
        state_store=state_store,
        previous_date=previous_date,
    )
    data_warning = previous_scope_data_file_warning(
        previous_date=previous_date,
        scope_label=scope.label,
        output_id=output_id,
        required_slices=non_empty_scope_slices(active_by_slice),
        available_slices=available_slices,
        download_enabled=read_authoritative,
    )
    if data_warning is not None:
        warning_recorder(data_warning)
    else:
        validation_summary.record_pass(
            rule_id=RULE_PREVIOUS_SCOPE_DATA_ID,
            message=f"previous business day scope data files confirmed for {output_id}",
            log=pass_log,
        )

    generated_paths: list[Path] = []
    for slice_token, snapshot_df in sorted(snapshot_by_slice.items()):
        current_active = active_by_slice[slice_token]
        previous_active = derive_active_noncompliant(
            snapshot_df, as_of_date=required_previous_day
        )
        if current_active.is_empty() and previous_active.is_empty():
            continue
        became_compliant = derive_daily_diff_frame(
            previous_active=previous_active,
            current_active=current_active,
            run_date=run_date,
            previous_date=previous_date,
            slice_token=slice_token,
            schema_root=schema_root,
        )
        became_compliant = project_delivery_contract(
            became_compliant,
            output_id=output_id,
            schema_root=schema_root,
        )
        output_path = (
            diff_dir
            / f"{run_date}_{previous_date}_panorama_{slice_token}_became_compliant.xlsx"
        )
        generated_paths.append(output_path)
        if io_mode.dry_run:
            continue
        ensure_dir(diff_dir)
        became_compliant.write_excel(output_path)

    uploaded_count = 0
    if io_mode.publish:
        if output_publisher is None:
            raise RuntimeError("Publish mode requires an output publisher.")
        uploaded = output_publisher.publish_files(
            destination_key="outputs.list_difference",
            paths=generated_paths,
            overwrite=True,
        )
        uploaded_count = len(uploaded)
    return generated_paths, uploaded_count


def write_pear_action_queue_xlsx_outputs(
    *,
    pear_state_dir: Path,
    pear_processed_dir: Path,
    run_date: str,
    output_id: str,
    scope: DeliveryScope,
    reference: SchoolReference,
    schema_root: Path,
    action_queue_dir: Path,
    io_mode: IOMode,
    output_publisher: OutputPublisher | None,
) -> tuple[list[Path], int]:
    emit_empty_action_queue_outputs = False
    try:
        action_queue_by_slice = load_scoped_pear_state_frames(
            pear_state_dir=pear_state_dir,
            state_name="suspension_vs_overdue",
            run_date=run_date,
            scope=scope,
            reference=reference,
        )
    except RuntimeError as exc:
        if "No PEAR suspension_vs_overdue state snapshots were found" not in str(exc):
            raise
        if not is_empty_processed_action_queue_snapshot(
            pear_processed_dir=pear_processed_dir,
            run_date=run_date,
        ):
            raise
        action_queue_by_slice = empty_action_queue_frames_for_scope(
            scope=scope,
            reference=reference,
        )
        emit_empty_action_queue_outputs = True
        logging.warning(
            "PEAR action queue fallback: processed action queue snapshot is present "
            "for run_date=%s but state snapshots are absent; emitting empty scoped "
            "action queue outputs.",
            run_date,
        )

    action_queue_total_rows = sum(
        frame.height for frame in action_queue_by_slice.values()
    )
    if action_queue_total_rows == 0:
        action_queue_by_slice = empty_action_queue_frames_for_scope(
            scope=scope,
            reference=reference,
        )
        emit_empty_action_queue_outputs = True
        per_slice_counts = ", ".join(
            f"{slice_token}:{frame.height}"
            for slice_token, frame in sorted(action_queue_by_slice.items())
        )
        logging.warning(
            "PEAR action queue delivery contains zero rows for scope=%s "
            "(run_date=%s). Emitting empty output file(s). Per-slice rows: %s",
            scope.label,
            run_date,
            per_slice_counts,
        )

    generated_paths: list[Path] = []
    for slice_token, frame in sorted(action_queue_by_slice.items()):
        if frame.is_empty() and not emit_empty_action_queue_outputs:
            continue
        delivery_frame = project_delivery_contract(
            frame,
            output_id=output_id,
            schema_root=schema_root,
        )
        output_path = action_queue_dir / f"{run_date}_{slice_token}_action_queue.xlsx"
        generated_paths.append(output_path)
        if io_mode.dry_run:
            continue
        ensure_dir(action_queue_dir)
        delivery_frame.write_excel(output_path)

    uploaded_count = 0
    if io_mode.publish:
        if output_publisher is None:
            raise RuntimeError("Publish mode requires an output publisher.")
        uploaded = output_publisher.publish_files(
            destination_key="outputs.action_queue",
            paths=generated_paths,
            overwrite=True,
        )
        uploaded_count = len(uploaded)
    return generated_paths, uploaded_count
