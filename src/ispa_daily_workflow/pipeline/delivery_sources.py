from __future__ import annotations

import argparse
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import polars as pl

from ispa_daily_workflow.compliance_history import (
    derive_active_noncompliant,
    read_compliance_history_frame,
)
from ispa_daily_workflow.domain.delivery.artifacts import format_output_path
from ispa_daily_workflow.domain.delivery.routing import (
    DeliveryScope,
    apply_scope_filter,
    resolve_compliance_history_paths_for_scope,
)
from ispa_daily_workflow.io.adapters import StateStore
from ispa_daily_workflow.io.workdays import load_workdays
from ispa_daily_workflow.pipeline.deliver_pear_state_sync import (
    sync_pear_state_from_store,
)
from ispa_daily_workflow.pipeline.delivery_config import DeliveryRunConfig
from ispa_daily_workflow.pipeline.delivery_runtime import IOMode
from ispa_daily_workflow.reference import SchoolReference
from ispa_daily_workflow.validation import (
    RULE_TEMPORAL_BOUNDS_ID,
    RuleResult,
    ValidationSummary,
    ensure_school_label_column,
    run_delivery_validations,
)


@dataclass(frozen=True)
class DeliverySourceFrames:
    snapshot_by_slice: dict[str, pl.DataFrame]
    active_by_slice: dict[str, pl.DataFrame]
    read_authoritative: bool


def load_delivery_source_frames(
    *,
    args: argparse.Namespace,
    config: DeliveryRunConfig,
    io_mode: IOMode,
    run_day: date,
    run_date: str,
    scope: DeliveryScope,
    reference: SchoolReference,
    state_store: StateStore | None,
    validation_summary: ValidationSummary,
    warning_recorder: Callable[[RuleResult], None],
    warning_details: list[str],
    continuity_waived_waves: set[str],
) -> DeliverySourceFrames:
    read_authoritative = io_mode.read_authoritative
    snapshot_by_slice: dict[str, pl.DataFrame] = {}
    active_by_slice: dict[str, pl.DataFrame] = {}
    pear_processed_dir = config.output_root / "pear_processed"
    pear_state_dir = config.output_root / "pear_state"

    if args.source == "panorama":
        if read_authoritative:
            if state_store is None:
                raise RuntimeError("Authoritative read mode requires a state store.")
            synced = state_store.download_latest_compliance_histories(
                compliance_history_dir=config.compliance_history_dir,
                run_date=run_date,
                purge_local_before_sync=True,
            )
            logging.info(
                "Synced %s compliance_history snapshot(s) from %s state store",
                len(synced),
                state_store.name,
            )
        elif io_mode.label == "local-only":
            logging.info(
                "No-download mode: using local compliance_history in %s",
                format_output_path(
                    config.compliance_history_dir,
                    verbose=args.verbose,
                ),
            )
        else:
            logging.info(
                "Dry-run mode: skipping authoritative state sync; using local "
                "compliance_history in %s",
                format_output_path(
                    config.compliance_history_dir,
                    verbose=args.verbose,
                ),
            )

        compliance_history_paths_by_slice = resolve_compliance_history_paths_for_scope(
            compliance_history_dir=config.compliance_history_dir,
            run_date=run_date,
            scope=scope,
            exact_run_date=True,
        )
        logging.info(
            "Resolved %s compliance_history slice(s) for scope %s",
            len(compliance_history_paths_by_slice),
            scope.label,
        )
        snapshot_by_slice, active_by_slice = load_scoped_frames(
            compliance_history_paths_by_slice=compliance_history_paths_by_slice,
            run_day=run_day,
            scope=scope,
            reference=reference,
            schema_root=config.schema_root,
            strict_headers=config.strict_headers,
            validation_summary=validation_summary,
            warning_recorder=warning_recorder,
        )
    elif read_authoritative:
        if state_store is None:
            raise RuntimeError("Authoritative read mode requires a state store.")
        synced_pear_state = sync_pear_state_from_store(
            state_store=state_store,
            run_date=run_date,
            schema_root=config.schema_root,
            reference=reference,
            workdays_path=config.workdays_path,
            pear_processed_dir=pear_processed_dir,
            pear_state_dir=pear_state_dir,
            continuity_waived_waves=continuity_waived_waves,
            strict_headers=config.strict_headers,
            verbose_warning_details=args.verbose,
            warning_details=warning_details,
        )
        logging.debug(
            "Synced %s PEAR state snapshot(s) for run_date=%s",
            len(synced_pear_state),
            run_date,
        )
    elif io_mode.label == "local-only":
        logging.info(
            "No-download mode: using local PEAR state snapshots in %s and PEAR processed snapshots in %s",
            format_output_path(pear_state_dir, verbose=args.verbose),
            format_output_path(pear_processed_dir, verbose=args.verbose),
        )
    else:
        logging.info(
            "Dry-run mode: skipping ADLS PEAR state sync; using local PEAR state in %s and PEAR processed in %s",
            format_output_path(pear_state_dir, verbose=args.verbose),
            format_output_path(pear_processed_dir, verbose=args.verbose),
        )

    return DeliverySourceFrames(
        snapshot_by_slice=snapshot_by_slice,
        active_by_slice=active_by_slice,
        read_authoritative=read_authoritative,
    )


def load_scoped_frames(
    *,
    compliance_history_paths_by_slice: dict[str, Path],
    run_day: date,
    scope: DeliveryScope,
    reference: SchoolReference,
    schema_root: Path,
    strict_headers: bool,
    validation_summary: ValidationSummary,
    warning_recorder: Callable[[RuleResult], None],
) -> tuple[dict[str, pl.DataFrame], dict[str, pl.DataFrame]]:
    snapshot_by_slice: dict[str, pl.DataFrame] = {}
    active_by_slice: dict[str, pl.DataFrame] = {}

    for slice_token, compliance_history_path in sorted(
        compliance_history_paths_by_slice.items()
    ):
        snapshot_df = ensure_school_label_column(
            read_compliance_history_frame(
                compliance_history_path,
                schema_root=schema_root,
                strict_headers=strict_headers,
            )
        )
        scoped_snapshot = apply_scope_filter(
            snapshot_df, scope=scope, reference=reference
        )
        snapshot_by_slice[slice_token] = scoped_snapshot
        validation_results = run_delivery_validations(
            stage="D-D",
            frame=scoped_snapshot,
            run_day=run_day,
            label=f"delivery snapshot {slice_token}",
        )
        if not validation_results:
            validation_summary.record_pass(
                rule_id=RULE_TEMPORAL_BOUNDS_ID,
                message=f"temporal bounds passed for delivery snapshot {slice_token}",
                log=logging.debug,
            )
        else:
            for result in validation_results:
                warning_recorder(result)
        active_by_slice[slice_token] = derive_active_noncompliant(
            scoped_snapshot, as_of_date=run_day
        )
    return snapshot_by_slice, active_by_slice


def previous_business_day(*, run_day: date, workdays_path: Path) -> date | None:
    if not workdays_path.exists():
        return None
    workdays = load_workdays(workdays_path)
    info = workdays.get(run_day)
    if info is None:
        return None
    return info.previous_business_day
