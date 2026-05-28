from __future__ import annotations

import argparse
import logging
from pathlib import Path

from panorama_compliance.io.adapters import (
    OutputPublisher,
    StateStore,
    load_output_publisher,
    load_state_store,
    sharepoint_settings_for_publisher,
)
from panorama_compliance.io.workdays import parse_run_date
from panorama_compliance.progress import configure_progress
from panorama_compliance.domain.delivery.artifacts import (
    pdf_school_status_counts as _pdf_school_status_counts,
)
from panorama_compliance.domain.delivery.pear_state import (
    empty_action_queue_frames_for_scope as _empty_action_queue_frames_for_scope,
    is_empty_processed_action_queue_snapshot as _is_empty_processed_action_queue_snapshot,
    resolve_pear_state_paths as _resolve_pear_state_paths,
)
from panorama_compliance.pipeline.delivery_dispatch import (
    dispatch_delivery_output as _dispatch_delivery_output,
)
from panorama_compliance.pipeline.delivery_config import load_delivery_config
from panorama_compliance.pipeline.delivery_runtime import (
    IOMode,
    prepare_delivery_roots as _prepare_delivery_roots,
    print_output_summary as _print_output_summary,
    resolve_continuity_waived_waves as _resolve_continuity_waived_waves,
    resolve_delivery_scope as _resolve_delivery_scope,
    resolve_pear_suspension_override as _resolve_pear_suspension_override,
    setup_delivery_logging as _setup_delivery_logging,
    write_warning_details_artifact as _write_warning_details_artifact,
)
from panorama_compliance.pipeline.delivery_sources import (
    load_delivery_source_frames as _load_delivery_source_frames,
    previous_business_day as _previous_business_day,
)
from panorama_compliance.domain.common.source_policy import (
    PANORAMA_ONLY_OUTPUT_IDS,
    PDF_OUTPUT_IDS,
    PEAR_ONLY_OUTPUT_IDS,
    SOURCE_CHOICES,
)
from panorama_compliance.domain.delivery.routing import (
    LOCKED_OUTPUT_IDS,
    parse_scope_selection,
)
from panorama_compliance.reference import load_school_reference
from panorama_compliance.validation import (
    RuleResult,
    ValidationSummary,
    all_rule_ids,
)

PROJECT_ROOT = Path(__file__).resolve().parents[3]

__all__ = [
    "_delivery_io_mode",
    "_empty_action_queue_frames_for_scope",
    "_is_empty_processed_action_queue_snapshot",
    "_load_delivery_adapters",
    "_parse_args",
    "_pdf_school_status_counts",
    "_resolve_pear_state_paths",
    "parse_scope_selection",
]


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Generate and publish exactly one scoped output from the selected state source. "
            "Requires one scope flag (--wave|--level|--school)."
        )
    )
    parser.add_argument(
        "output_id",
        choices=LOCKED_OUTPUT_IDS,
        help="Output identifier (destination.type.format).",
    )
    parser.add_argument(
        "--source",
        required=True,
        choices=SOURCE_CHOICES,
        help=(
            "Required output source policy. "
            "Use panorama for compliance_history-backed outputs and pear for PEAR state outputs."
        ),
    )
    parser.add_argument(
        "--run-date",
        required=True,
        type=str,
        help="Run date in YYYYMMDD format.",
    )
    scope_group = parser.add_mutually_exclusive_group(required=True)
    scope_group.add_argument(
        "--wave",
        type=str,
        help="Wave scope value from school_reference (or ALL).",
    )
    scope_group.add_argument(
        "--level",
        type=str,
        help="Level scope value from school_reference (or ALL).",
    )
    scope_group.add_argument(
        "--school",
        type=str,
        help="School scope value or ALL.",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("profile/config.yaml"),
        help="Path to config file (default: ./profile/config.yaml).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Compute and validate output candidates without writes/uploads/deletes.",
    )
    parser.add_argument(
        "--upload",
        action=argparse.BooleanOptionalAction,
        default=True,
        help=(
            "Upload generated outputs to SharePoint destinations (default: enabled)."
        ),
    )
    parser.add_argument(
        "--download",
        action=argparse.BooleanOptionalAction,
        default=True,
        help=(
            "Download authoritative input state from ADLS before delivery "
            "(default: enabled)."
        ),
    )
    parser.add_argument(
        "--cleanup-sharepoint-pdfs",
        action="store_true",
        help=(
            "Delete existing overdue/suspension list PDFs in target SharePoint school folders "
            "before upload. For --dry-run, list files that would be removed."
        ),
    )
    parser.add_argument(
        "--retain-typst-artifacts",
        action="store_true",
        help=(
            "Keep generated Typst source artifacts (.typ). "
            "Default behavior removes them after report generation."
        ),
    )
    parser.add_argument(
        "--progress",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Show progress bars for slow operations (default: auto when interactive).",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable debug logs, including third-party HTTP request logs.",
    )
    parser.add_argument(
        "--pear-suspension-file",
        type=Path,
        default=None,
        help=(
            "Optional PEAR suspension operational parquet override for "
            "sharepoint.suspension.pdf delivery. Intended for one-off cutover "
            "patch workflows."
        ),
    )
    parser.add_argument(
        "--allow-missing-prior-suspension-continuity",
        action="store_true",
        help=(
            "Bootstrap mode for PEAR suspension continuity: allow missing previous "
            "business day suspension list for the selected scope only. "
            "Requires --source pear, output_id sharepoint.suspension.pdf, "
            "a non-ALL scope, and --no-upload."
        ),
    )
    args = parser.parse_args(argv)
    try:
        _delivery_io_mode(args)
    except ValueError as exc:
        parser.error(str(exc))
    if args.cleanup_sharepoint_pdfs and not args.upload and not args.dry_run:
        parser.error("--cleanup-sharepoint-pdfs requires --upload (or --dry-run)")
    if args.cleanup_sharepoint_pdfs and args.output_id not in PDF_OUTPUT_IDS:
        parser.error(
            "--cleanup-sharepoint-pdfs requires output_id "
            "sharepoint.overdue.pdf or sharepoint.suspension.pdf"
        )
    if args.output_id in PANORAMA_ONLY_OUTPUT_IDS and args.source != "panorama":
        parser.error(f"{args.output_id} requires --source panorama")
    if args.output_id in PEAR_ONLY_OUTPUT_IDS and args.source != "pear":
        parser.error(f"{args.output_id} requires --source pear")
    if args.pear_suspension_file is not None and not (
        args.source == "pear" and args.output_id == "sharepoint.suspension.pdf"
    ):
        parser.error(
            "--pear-suspension-file requires --source pear and "
            "output_id sharepoint.suspension.pdf"
        )
    if args.allow_missing_prior_suspension_continuity:
        if not (
            args.source == "pear" and args.output_id == "sharepoint.suspension.pdf"
        ):
            parser.error(
                "--allow-missing-prior-suspension-continuity requires --source pear "
                "and output_id sharepoint.suspension.pdf"
            )
        if args.upload:
            parser.error(
                "--allow-missing-prior-suspension-continuity requires --no-upload"
            )
        scope_value = (
            args.wave
            if args.wave is not None
            else (args.level if args.level is not None else args.school)
        )
        if str(scope_value or "").strip().upper() == "ALL":
            parser.error(
                "--allow-missing-prior-suspension-continuity requires a non-ALL "
                "scope (--wave/--level/--school)"
            )
    return args


def _delivery_io_mode(args: argparse.Namespace) -> IOMode:
    return IOMode.for_delivery(
        dry_run=bool(args.dry_run),
        upload=bool(args.upload),
        download=bool(args.download),
    )


def _load_delivery_adapters(
    *,
    config: dict,
    io_mode: IOMode,
    needs_sharepoint_cleanup: bool,
) -> tuple[StateStore | None, OutputPublisher | None, object | None]:
    state_store = load_state_store(config) if io_mode.read_authoritative else None
    output_publisher = load_output_publisher(config) if io_mode.publish else None
    sharepoint_settings = sharepoint_settings_for_publisher(output_publisher)
    if needs_sharepoint_cleanup and sharepoint_settings is None:
        output_publisher = load_output_publisher(config)
        sharepoint_settings = sharepoint_settings_for_publisher(output_publisher)
    return state_store, output_publisher, sharepoint_settings


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    io_mode = _delivery_io_mode(args)
    configure_progress(args.progress)
    run_day = parse_run_date(args.run_date)
    run_date = run_day.strftime("%Y%m%d")
    validation_summary = ValidationSummary(tracked_rule_ids=all_rule_ids())
    warning_details: list[str] = []

    def record_warning(result: RuleResult) -> None:
        validation_summary.record_warning(result, log=logging.warning)
        warning_details.append(
            f"VALIDATION WARN [{result.rule_id}] {str(result.message).strip()}"
        )

    delivery_config = load_delivery_config(args, project_root=PROJECT_ROOT)
    reference = load_school_reference(delivery_config.reference_path)
    try:
        scope = _resolve_delivery_scope(args=args, reference=reference)
        continuity_waived_waves = _resolve_continuity_waived_waves(
            args=args,
            scope=scope,
            reference=reference,
        )
    except ValueError as exc:
        print(str(exc))
        return 2

    _setup_delivery_logging(
        args=args,
        config=delivery_config,
        run_date=run_date,
        scope=scope,
        continuity_waived_waves=continuity_waived_waves,
    )
    roots = _prepare_delivery_roots(
        args=args,
        config=delivery_config,
        io_mode=io_mode,
        run_date=run_date,
        scope=scope,
    )
    try:
        state_store, output_publisher, sharepoint_settings = _load_delivery_adapters(
            config=delivery_config.config,
            io_mode=io_mode,
            needs_sharepoint_cleanup=args.cleanup_sharepoint_pdfs,
        )
    except ValueError as exc:
        print(str(exc))
        return 2
    pear_suspension_override = _resolve_pear_suspension_override(args)
    source_frames = _load_delivery_source_frames(
        args=args,
        config=delivery_config,
        io_mode=io_mode,
        run_day=run_day,
        run_date=run_date,
        scope=scope,
        reference=reference,
        state_store=state_store,
        validation_summary=validation_summary,
        warning_recorder=record_warning,
        warning_details=warning_details,
        continuity_waived_waves=continuity_waived_waves,
    )
    previous_day = _previous_business_day(
        run_day=run_day,
        workdays_path=delivery_config.workdays_path,
    )
    pass_log = logging.info if args.verbose else logging.debug
    delivery_result = _dispatch_delivery_output(
        args=args,
        config=delivery_config,
        io_mode=io_mode,
        roots=roots,
        source_frames=source_frames,
        run_day=run_day,
        run_date=run_date,
        previous_day=previous_day,
        scope=scope,
        reference=reference,
        state_store=state_store,
        output_publisher=output_publisher,
        sharepoint_settings=sharepoint_settings,
        pear_suspension_override=pear_suspension_override,
        validation_summary=validation_summary,
        warning_recorder=record_warning,
        pass_log=pass_log,
        project_root=PROJECT_ROOT,
    )

    warning_details_artifact = _write_warning_details_artifact(
        warning_details=warning_details,
        artifacts_root=roots.report_artifacts_root,
        run_date=run_date,
        output_id=args.output_id,
        source=args.source,
        scope=scope,
    )
    validation_warning_details_count = sum(
        1 for detail in warning_details if detail.startswith("VALIDATION WARN [")
    )
    runtime_warning_details_count = (
        len(warning_details) - validation_warning_details_count
    )

    _print_output_summary(
        io_mode=io_mode,
        verbose=args.verbose,
        output_id=args.output_id,
        source=args.source,
        scope=scope,
        generated_paths=delivery_result.generated_paths,
        uploaded_count=delivery_result.uploaded_count,
        cleanup_sharepoint_pdfs=args.cleanup_sharepoint_pdfs,
        sharepoint_cleanup_entries=delivery_result.sharepoint_cleanup_entries,
        validation_summary=validation_summary,
        local_inspection_root=roots.local_inspection_root,
        suspension_totals=delivery_result.suspension_totals,
        rescind_diagnostics=delivery_result.rescind_diagnostics,
        warning_details_count=len(warning_details),
        validation_warning_details_count=validation_warning_details_count,
        runtime_warning_details_count=runtime_warning_details_count,
        warning_details_artifact=warning_details_artifact,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
