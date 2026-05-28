from __future__ import annotations

import argparse
import logging
import shlex
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

from panorama_compliance.config import ensure_dir
from panorama_compliance.domain.common.source_policy import PDF_OUTPUT_IDS
from panorama_compliance.domain.delivery.artifacts import (
    format_cleanup_entry,
    format_output_path,
    pdf_school_status_counts,
    resolve_local_inspection_root,
    sanitize_path_component,
)
from panorama_compliance.domain.delivery.pear_state import scope_waves
from panorama_compliance.domain.delivery.routing import (
    DeliveryScope,
    parse_scope_selection,
)
from panorama_compliance.io.local_artifacts import (
    clear_directory,
    run_retention_cleanup,
)
from panorama_compliance.logging import setup_logging
from panorama_compliance.pipeline.delivery_config import DeliveryRunConfig
from panorama_compliance.reference import (
    SchoolReference,
    collect_scope_values,
)
from panorama_compliance.validation import ValidationSummary


@dataclass(frozen=True)
class IOMode:
    label: str
    dry_run: bool
    read_authoritative: bool
    publish: bool
    write_local_outputs: bool

    @classmethod
    def for_delivery(
        cls,
        *,
        dry_run: bool,
        upload: bool,
        download: bool,
    ) -> "IOMode":
        if upload and not download:
            raise ValueError("--upload requires --download")
        if dry_run:
            return cls(
                label="dry-run",
                dry_run=True,
                read_authoritative=False,
                publish=False,
                write_local_outputs=False,
            )
        if upload:
            return cls(
                label="publish",
                dry_run=False,
                read_authoritative=True,
                publish=True,
                write_local_outputs=True,
            )
        if download:
            return cls(
                label="read-authoritative",
                dry_run=False,
                read_authoritative=True,
                publish=False,
                write_local_outputs=True,
            )
        return cls(
            label="local-only",
            dry_run=False,
            read_authoritative=False,
            publish=False,
            write_local_outputs=True,
        )

    @classmethod
    def for_update(cls, *, dry_run: bool) -> "IOMode":
        if dry_run:
            return cls(
                label="dry-run",
                dry_run=True,
                read_authoritative=False,
                publish=False,
                write_local_outputs=False,
            )
        return cls(
            label="publish",
            dry_run=False,
            read_authoritative=True,
            publish=True,
            write_local_outputs=True,
        )


@dataclass(frozen=True)
class DeliveryRoots:
    output_root: Path
    report_artifacts_root: Path
    diff_dir: Path
    action_queue_dir: Path
    reports_dir: Path
    local_inspection_root: Path | None


def resolve_debug_http(*, verbose: bool, logging_cfg: dict[str, object]) -> bool:
    return verbose or bool(logging_cfg.get("debug_http_requests", False))


def resolve_delivery_scope(
    *,
    args: argparse.Namespace,
    reference: SchoolReference,
) -> DeliveryScope:
    allowed_waves, allowed_levels = collect_scope_values(reference)
    return parse_scope_selection(
        wave=args.wave,
        level=args.level,
        school=args.school,
        allowed_waves=allowed_waves,
        allowed_levels=allowed_levels,
    )


def resolve_continuity_waived_waves(
    *,
    args: argparse.Namespace,
    scope: DeliveryScope,
    reference: SchoolReference,
) -> set[str]:
    if not args.allow_missing_prior_suspension_continuity:
        return set()
    waived_waves = scope_waves(scope=scope, reference=reference)
    if not waived_waves:
        raise ValueError(
            "Could not resolve scope waves for "
            "--allow-missing-prior-suspension-continuity."
        )
    return waived_waves


def setup_delivery_logging(
    *,
    args: argparse.Namespace,
    config: DeliveryRunConfig,
    run_date: str,
    scope: DeliveryScope,
    continuity_waived_waves: set[str],
) -> None:
    level_value = str(config.logging_cfg.get("level", "INFO")).upper()
    configured_level = getattr(logging, level_value, logging.INFO)
    level = logging.DEBUG if args.verbose else configured_level
    redact_long_numeric_ids_raw = config.logging_cfg.get("redact_long_numeric_ids")
    if (
        redact_long_numeric_ids_raw is None
        and "include_sensitive_ids" in config.logging_cfg
    ):
        redact_long_numeric_ids_raw = not bool(
            config.logging_cfg.get("include_sensitive_ids", True)
        )
    timezone_value = config.run_cfg.get("timezone")
    timezone_name = str(timezone_value) if timezone_value is not None else None
    setup_logging(
        None if args.dry_run else f"{run_date}_deliver_outputs.log",
        log_dir=config.logs_root,
        level=level,
        fmt=str(config.logging_cfg.get("format", "text")),
        redact_long_numeric_ids=bool(redact_long_numeric_ids_raw),
        debug_http=resolve_debug_http(
            verbose=args.verbose,
            logging_cfg=config.logging_cfg,
        ),
        timezone_name=timezone_name,
    )
    if continuity_waived_waves:
        logging.warning(
            "PEAR continuity bootstrap bypass enabled for scope %s: waived_waves=%s",
            scope.label,
            ", ".join(sorted(continuity_waived_waves)),
        )


def prepare_delivery_roots(
    *,
    args: argparse.Namespace,
    config: DeliveryRunConfig,
    io_mode: IOMode,
    run_date: str,
    scope: DeliveryScope,
) -> DeliveryRoots:
    if not io_mode.dry_run:
        retention_summary = run_retention_cleanup(
            output_root=config.output_root,
            artifacts_root=config.artifacts_root,
            input_root=config.input_root,
            today=date.today(),
        )
        logging.debug(
            "Retention cleanup complete: inspect_run_dirs_removed=%s "
            "state_sync_run_dirs_removed=%s data_quality_files_removed=%s",
            retention_summary["inspect_run_dirs_removed"],
            retention_summary["state_sync_run_dirs_removed"],
            retention_summary["data_quality_files_removed"],
        )

    delivery_output_root = config.output_root
    report_artifacts_root = config.artifacts_root
    local_inspection_root: Path | None = None
    if not args.upload:
        local_inspection_root = resolve_local_inspection_root(
            output_root=config.output_root,
            run_date=run_date,
            source=args.source,
            upload_enabled=args.upload,
            download_enabled=args.download,
            output_id=args.output_id,
            scope=scope,
        )
        if not io_mode.dry_run and local_inspection_root.exists():
            clear_directory(local_inspection_root)
            logging.debug(
                "No-upload mode: cleared %s",
                format_output_path(local_inspection_root, verbose=args.verbose),
            )
        delivery_output_root = local_inspection_root / "output"
        report_artifacts_root = local_inspection_root / "artifacts"
        if not io_mode.dry_run:
            local_inspection_root.mkdir(parents=True, exist_ok=True)
        cleanup_cmd = f"rm -rf {shlex.quote(str(local_inspection_root))}"
        logging.debug(
            "No-upload mode: %s %s -> %s",
            args.output_id,
            scope.label,
            format_output_path(local_inspection_root, verbose=args.verbose),
        )
        if args.verbose:
            logging.debug("To clear local inspection outputs later: %s", cleanup_cmd)

    return DeliveryRoots(
        output_root=delivery_output_root,
        report_artifacts_root=report_artifacts_root,
        diff_dir=delivery_output_root / "diffs",
        action_queue_dir=delivery_output_root / "action_queue",
        reports_dir=delivery_output_root / "reports",
        local_inspection_root=local_inspection_root,
    )


def resolve_pear_suspension_override(args: argparse.Namespace) -> Path | None:
    if args.pear_suspension_file is None:
        return None
    candidate = args.pear_suspension_file
    if not candidate.is_absolute():
        candidate = (Path.cwd() / candidate).resolve()
    if not candidate.exists():
        raise FileNotFoundError(f"--pear-suspension-file was not found: {candidate}")
    return candidate


def write_warning_details_artifact(
    *,
    warning_details: list[str],
    artifacts_root: Path,
    run_date: str,
    output_id: str,
    source: str,
    scope: DeliveryScope,
) -> Path | None:
    if not warning_details:
        return None
    warning_dir = ensure_dir(artifacts_root / "warnings")
    timestamp = datetime.now().strftime("%Y%m%dT%H%M%S")
    scope_value = "ALL" if scope.is_all else scope.normalized_value
    output_token = sanitize_path_component(output_id)
    scope_token = sanitize_path_component(f"{scope.dimension}_{scope_value}")
    source_token = sanitize_path_component(source)
    artifact_path = (
        warning_dir
        / f"{timestamp}_{run_date}_{source_token}_{output_token}_{scope_token}.txt"
    )
    lines = [
        f"run_date={run_date}",
        f"source={source}",
        f"output_id={output_id}",
        f"scope={scope.label}",
        f"warning_count={len(warning_details)}",
        "",
    ]
    lines.extend(warning_details)
    artifact_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return artifact_path


def print_output_summary(
    *,
    io_mode: IOMode,
    verbose: bool,
    output_id: str,
    source: str,
    scope: DeliveryScope,
    generated_paths: list[Path],
    uploaded_count: int,
    cleanup_sharepoint_pdfs: bool,
    sharepoint_cleanup_entries: list[str],
    validation_summary: ValidationSummary,
    local_inspection_root: Path | None = None,
    suspension_totals: dict[str, int] | None = None,
    rescind_diagnostics: dict[str, int] | None = None,
    warning_details_count: int = 0,
    validation_warning_details_count: int = 0,
    runtime_warning_details_count: int = 0,
    warning_details_artifact: Path | None = None,
) -> None:
    print(f"Output ID: {output_id}")
    print(f"Source: {source}")
    print(f"Scope: {scope.label}")
    print(f"Mode: {io_mode.label}")
    print("Summary:")
    print(f"  Generated candidates: {len(generated_paths)}")
    if output_id == "sharepoint.suspension.pdf" and suspension_totals is not None:
        print(
            "  Suspension list totals: "
            f"active={suspension_totals['active_suspensions']} "
            f"newly_rescinded={suspension_totals['newly_rescinded']}"
        )
    if output_id == "sharepoint.suspension.pdf" and rescind_diagnostics is not None:
        print(
            "  Rescind diagnostics: "
            f"transitions={rescind_diagnostics['rescinds_transition_count']} "
            "date_shift_only="
            f"{rescind_diagnostics['rescinds_date_shift_only_count']} "
            f"prior_active={rescind_diagnostics['prior_active_count']} "
            f"current_active={rescind_diagnostics['current_active_count']}"
        )
    if output_id in PDF_OUTPUT_IDS:
        final_count, list_count = pdf_school_status_counts(generated_paths)
        print(
            "  School status counts: "
            f"final_summary={final_count} "
            f"list_status={list_count}"
        )
    if io_mode.dry_run or not io_mode.publish:
        print("  Uploads performed: 0")
    else:
        print(f"  Uploads performed: {uploaded_count}")
    if cleanup_sharepoint_pdfs:
        label = (
            "SharePoint cleanup candidates"
            if io_mode.dry_run
            else "SharePoint files deleted"
        )
        print(f"  {label}: {len(sharepoint_cleanup_entries)}")
    print("Warnings:")
    print(
        "  Captured: "
        f"total={warning_details_count} "
        f"validation={validation_warning_details_count} "
        f"runtime={runtime_warning_details_count}"
    )
    print("Validation:")
    print(
        "  Status: "
        f"{validation_summary.status} "
        f"(applied={validation_summary.applied}, "
        f"pass={validation_summary.passed}, "
        f"warn={validation_summary.warned}, "
        f"fail={validation_summary.failed})"
    )
    rule_counts = validation_summary.rule_status_counts()
    print(
        "  Rules: "
        f"PASS={rule_counts.get('PASS', 0)} "
        f"WARN={rule_counts.get('WARN', 0)} "
        f"FAIL={rule_counts.get('FAIL', 0)} "
        f"NONE={rule_counts.get('NONE', 0)}"
    )
    print("Artifacts:")
    if verbose and generated_paths:
        print(f"  Generated files: {len(generated_paths)}")
        for path in generated_paths:
            display_value = format_output_path(path, verbose=True)
            print(f"    - {display_value}")
    if verbose and cleanup_sharepoint_pdfs and sharepoint_cleanup_entries:
        print(f"  Cleanup files: {len(sharepoint_cleanup_entries)}")
        for entry in sharepoint_cleanup_entries:
            print(f"    - {format_cleanup_entry(entry, verbose=True)}")
    if warning_details_artifact is not None:
        warning_artifact_display = format_output_path(
            warning_details_artifact, verbose=verbose
        )
        print(f"  Warning details artifact: {warning_artifact_display}")
    if not io_mode.publish and local_inspection_root is not None:
        cleanup_target = format_output_path(local_inspection_root, verbose=verbose)
        cleanup_cmd = f"rm -rf {shlex.quote(str(local_inspection_root))}"
        print(f"  Local inspection root: {cleanup_target}")
        print(f"  To clear local inspection outputs: {cleanup_cmd}")
