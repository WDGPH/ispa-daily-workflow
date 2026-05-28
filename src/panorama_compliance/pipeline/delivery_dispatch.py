from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Callable

from panorama_compliance.domain.common.source_policy import PANORAMA_DIFF_OUTPUT_IDS
from panorama_compliance.domain.delivery.routing import DeliveryScope
from panorama_compliance.io.adapters import OutputPublisher, StateStore
from panorama_compliance.pipeline.deliver_pdf_outputs import (
    write_overdue_pdf_outputs,
    write_suspension_pdf_outputs,
)
from panorama_compliance.pipeline.deliver_tabular_outputs import (
    write_panorama_diff_xlsx_outputs,
    write_pear_action_queue_xlsx_outputs,
)
from panorama_compliance.pipeline.delivery_config import DeliveryRunConfig
from panorama_compliance.pipeline.delivery_runtime import DeliveryRoots, IOMode
from panorama_compliance.pipeline.delivery_sources import DeliverySourceFrames
from panorama_compliance.reference import SchoolReference
from panorama_compliance.validation import (
    RuleResult,
    ValidationSummary,
)


@dataclass(frozen=True)
class DeliveryOutputResult:
    generated_paths: list[Path]
    uploaded_count: int
    sharepoint_cleanup_entries: list[str]
    suspension_totals: dict[str, int] | None = None
    rescind_diagnostics: dict[str, int] | None = None


def dispatch_delivery_output(
    *,
    args: argparse.Namespace,
    config: DeliveryRunConfig,
    io_mode: IOMode,
    roots: DeliveryRoots,
    source_frames: DeliverySourceFrames,
    run_day: date,
    run_date: str,
    previous_day: date | None,
    scope: DeliveryScope,
    reference: SchoolReference,
    state_store: StateStore | None,
    output_publisher: OutputPublisher | None,
    sharepoint_settings,
    pear_suspension_override: Path | None,
    validation_summary: ValidationSummary,
    warning_recorder: Callable[[RuleResult], None],
    pass_log: Callable[[str], None],
    project_root: Path,
) -> DeliveryOutputResult:
    pear_processed_dir = config.output_root / "pear_processed"
    pear_state_dir = config.output_root / "pear_state"
    sharepoint_cleanup_entries: list[str] = []

    if args.output_id in PANORAMA_DIFF_OUTPUT_IDS:
        generated_paths, uploaded_count = write_panorama_diff_xlsx_outputs(
            snapshot_by_slice=source_frames.snapshot_by_slice,
            active_by_slice=source_frames.active_by_slice,
            previous_day=previous_day,
            run_date=run_date,
            output_id=args.output_id,
            scope=scope,
            schema_root=config.schema_root,
            diff_dir=roots.diff_dir,
            io_mode=io_mode,
            read_authoritative=source_frames.read_authoritative,
            compliance_history_dir=config.compliance_history_dir,
            state_store=state_store,
            output_publisher=output_publisher,
            validation_summary=validation_summary,
            warning_recorder=warning_recorder,
            pass_log=pass_log,
        )
        return DeliveryOutputResult(
            generated_paths=generated_paths,
            uploaded_count=uploaded_count,
            sharepoint_cleanup_entries=[],
        )

    if args.output_id == "sharepoint.action_queue.xlsx":
        generated_paths, uploaded_count = write_pear_action_queue_xlsx_outputs(
            pear_state_dir=pear_state_dir,
            pear_processed_dir=pear_processed_dir,
            run_date=run_date,
            output_id=args.output_id,
            scope=scope,
            reference=reference,
            schema_root=config.schema_root,
            action_queue_dir=roots.action_queue_dir,
            io_mode=io_mode,
            output_publisher=output_publisher,
        )
        return DeliveryOutputResult(
            generated_paths=generated_paths,
            uploaded_count=uploaded_count,
            sharepoint_cleanup_entries=[],
        )

    if args.output_id == "sharepoint.overdue.pdf":
        pdf_result = write_overdue_pdf_outputs(
            source=args.source,
            active_by_slice=source_frames.active_by_slice,
            pear_state_dir=pear_state_dir,
            run_date=run_date,
            run_day=run_day,
            previous_day=previous_day,
            output_id=args.output_id,
            scope=scope,
            reference=reference,
            reports_dir=roots.reports_dir,
            report_artifacts_root=roots.report_artifacts_root,
            logo_path=config.logo_path,
            typst_bin=config.typst_bin,
            project_root=project_root,
            privacy_notice_path=config.privacy_notice_path,
            school_year_start_month=config.school_year_start_month,
            sharepoint_settings=sharepoint_settings,
            io_mode=io_mode,
            cleanup_sharepoint_pdfs=args.cleanup_sharepoint_pdfs,
            retain_typst_artifacts=args.retain_typst_artifacts,
            verbose=args.verbose,
            validation_summary=validation_summary,
            pass_log=pass_log,
        )
        sharepoint_cleanup_entries.extend(pdf_result.cleanup_entries)
        return DeliveryOutputResult(
            generated_paths=pdf_result.generated_paths,
            uploaded_count=pdf_result.uploaded_count,
            sharepoint_cleanup_entries=sharepoint_cleanup_entries,
        )

    if args.output_id == "sharepoint.suspension.pdf":
        pdf_result = write_suspension_pdf_outputs(
            source=args.source,
            snapshot_by_slice=source_frames.snapshot_by_slice,
            pear_state_dir=pear_state_dir,
            pear_processed_dir=pear_processed_dir,
            pear_suspension_override=pear_suspension_override,
            run_date=run_date,
            run_day=run_day,
            previous_day=previous_day,
            output_id=args.output_id,
            scope=scope,
            reference=reference,
            compliance_history_dir=config.compliance_history_dir,
            state_store=state_store,
            read_authoritative=source_frames.read_authoritative,
            reports_dir=roots.reports_dir,
            report_artifacts_root=roots.report_artifacts_root,
            logo_path=config.logo_path,
            typst_bin=config.typst_bin,
            project_root=project_root,
            privacy_notice_path=config.privacy_notice_path,
            school_year_start_month=config.school_year_start_month,
            sharepoint_settings=sharepoint_settings,
            io_mode=io_mode,
            cleanup_sharepoint_pdfs=args.cleanup_sharepoint_pdfs,
            retain_typst_artifacts=args.retain_typst_artifacts,
            verbose=args.verbose,
            validation_summary=validation_summary,
            warning_recorder=warning_recorder,
            pass_log=pass_log,
        )
        sharepoint_cleanup_entries.extend(pdf_result.cleanup_entries)
        return DeliveryOutputResult(
            generated_paths=pdf_result.generated_paths,
            uploaded_count=pdf_result.uploaded_count,
            sharepoint_cleanup_entries=sharepoint_cleanup_entries,
            suspension_totals=pdf_result.suspension_totals,
            rescind_diagnostics=pdf_result.rescind_diagnostics,
        )

    raise RuntimeError(
        f"Unsupported output_id after parser validation: {args.output_id}"
    )
