from __future__ import annotations

import argparse
import logging
from datetime import datetime
from pathlib import Path

from azure.storage.filedatalake import FileSystemClient

PROJECT_ROOT = Path(__file__).resolve().parents[3]

from ispa_daily_workflow.config import ensure_dir
from ispa_daily_workflow.domain.pear.intake import (
    REPORT_SUSPENSION,
    discover_input_files,
    extract_canonical_landing_report,
    extract_landing_report,
    resolve_suspension_canonical_filename,
    transform_report,
    validate_landing_schema,
    validate_processed_schema,
)
from ispa_daily_workflow.io.adls import (
    get_file_system_client,
    load_adls_settings,
)
from ispa_daily_workflow.io.sharepoint_settings import load_sharepoint_settings
from ispa_daily_workflow.logging import setup_logging
from ispa_daily_workflow.pipeline.pear_intake_outputs import (
    _partition_processed_frame_by_wave,
    _processed_wave_filename,
    _ProcessedFile,
    _resolve_optional_prefix,
    _warn_overwrite,
    _write_outputs,
)
from ispa_daily_workflow.pipeline.pear_intake_rescinds import (
    _patch_processed_suspension_rescinds,
)
from ispa_daily_workflow.pipeline.pear_intake_sources import (
    _PEAR_SHAREPOINT_SOURCE_KEYS,
    _download_sharepoint_sources,
    _resolve_pear_source_keys,
)
from ispa_daily_workflow.pipeline.workflow_config import load_workflow_config
from ispa_daily_workflow.quality import write_manifest
from ispa_daily_workflow.reference import load_school_reference
from ispa_daily_workflow.schema import ValidationError
from ispa_daily_workflow.validation import (
    RULE_PARSE_DIAGNOSTICS_ID,
    RULE_PEAR_DELETE_ACTION_MATCH_ID,
    RULE_PEAR_SUSPENSION_SUFFIX_AUTHORITY_ID,
    RULE_PEAR_WAVE_WINDOW_AUTHORITY_ID,
    RuleResult,
    ValidationSummary,
    all_rule_ids,
    delete_action_match_warning,
    require_wave_window_authority,
)

_RULE_PEAR_RUNTIME_CONFIG_ID = "ISPA-05-003"
_RULE_PEAR_LANDING_SCHEMA_ID = "ISPA-01-001"
_RULE_PEAR_PROCESSED_SCHEMA_ID = "ISPA-01-002"


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Ingest PEAR report exports from a local folder into canonical landing "
            "and processed outputs, with optional ADLS upload."
        )
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("profile/config.yaml"),
        help="Path to config file (default: ./profile/config.yaml).",
    )
    parser.add_argument(
        "--input-dir",
        type=Path,
        default=None,
        help=(
            "Directory containing PEAR XLSX files "
            "(default: <paths.input_root>/pear_intake)."
        ),
    )
    parser.add_argument(
        "--download-from-sharepoint",
        action=argparse.BooleanOptionalAction,
        default=False,
        help=(
            "Download PEAR XLSX sources from configured SharePoint destination(s) "
            "into --input-dir before intake."
        ),
    )
    parser.add_argument(
        "--sharepoint-source-key",
        action="append",
        choices=_PEAR_SHAREPOINT_SOURCE_KEYS,
        default=None,
        help=(
            "Optional source key(s) to download from when --download-from-sharepoint "
            "is enabled. Repeat for multiple keys. Defaults to all configured "
            "PEAR source keys."
        ),
    )
    parser.add_argument(
        "--overwrite-downloaded",
        action=argparse.BooleanOptionalAction,
        default=True,
        help=(
            "When downloading from SharePoint, overwrite local files in --input-dir "
            "with matching names."
        ),
    )
    parser.add_argument(
        "--schema-root",
        type=Path,
        default=None,
        help="Schema root override (default: config validation.schemas).",
    )
    parser.add_argument(
        "--reference-path",
        type=Path,
        default=None,
        help="School reference override (default: config paths.reference).",
    )
    parser.add_argument(
        "--landing-output-dir",
        type=Path,
        default=None,
        help=(
            "Landing output folder override (default: <paths.input_root>/pear_landing)."
        ),
    )
    parser.add_argument(
        "--processed-output-dir",
        type=Path,
        default=None,
        help=(
            "Processed output folder override "
            "(default: <paths.output_root>/pear_processed)."
        ),
    )
    parser.add_argument(
        "--write-landing",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Write canonical landing outputs locally.",
    )
    parser.add_argument(
        "--write-processed",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Write canonical processed outputs locally.",
    )
    parser.add_argument(
        "--upload-to-adls",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Upload generated landing/processed outputs to ADLS.",
    )
    parser.add_argument(
        "--landing-prefix",
        type=str,
        default=None,
        help=(
            "ADLS PEAR landing prefix override. Default: "
            "io.adls.destinations.pear_landing_prefix."
        ),
    )
    parser.add_argument(
        "--processed-prefix",
        type=str,
        default=None,
        help=(
            "ADLS PEAR processed prefix override. Default: "
            "io.adls.destinations.pear_processed_prefix."
        ),
    )
    parser.add_argument(
        "--landing-only",
        action="store_true",
        help="Run only landing extraction/validation/output stages.",
    )
    parser.add_argument(
        "--processed-only",
        action="store_true",
        help=(
            "Run only processed transform/output stages using canonical landing XLSX "
            "inputs from --input-dir."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate and summarize only; skip local writes and ADLS uploads.",
    )
    parser.add_argument(
        "--fail-fast",
        action="store_true",
        help="Stop after first file failure.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable verbose logging.",
    )
    args = parser.parse_args(argv)

    if args.landing_only and args.processed_only:
        parser.error("--landing-only cannot be combined with --processed-only")
    if args.processed_only and args.download_from_sharepoint:
        parser.error(
            "--processed-only cannot be combined with --download-from-sharepoint"
        )

    if args.landing_only:
        args.write_processed = False
    if args.processed_only:
        args.write_landing = False

    if args.upload_to_adls and not args.write_landing and not args.write_processed:
        parser.error(
            "--upload-to-adls requires at least one enabled writer "
            "(--write-landing or --write-processed)"
        )

    return args


def _resolve_debug_http(*, verbose: bool, logging_cfg: dict[str, object]) -> bool:
    return verbose or bool(logging_cfg.get("debug_http_requests", False))


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    runtime = load_workflow_config(args, project_root=PROJECT_ROOT)

    schema_root = args.schema_root or runtime.validation_path("schemas")
    reference_path = args.reference_path or runtime.required_path("reference")
    runtime.validate_files(
        reference_path=reference_path,
    )

    input_root = runtime.required_path("input_root")
    output_root = runtime.required_path("output_root")
    logs_root = runtime.required_path("logs_root")
    artifacts_root = runtime.required_path("artifacts_root")

    landing_output_dir = args.landing_output_dir or (input_root / "pear_landing")
    processed_output_dir = args.processed_output_dir or (output_root / "pear_processed")
    input_dir = args.input_dir or (input_root / "pear_intake")

    level_value = str(runtime.logging_cfg.get("level", "INFO")).upper()
    configured_level = getattr(logging, level_value, logging.INFO)
    level = logging.DEBUG if args.verbose else configured_level
    redact_long_numeric_ids_raw = runtime.logging_cfg.get("redact_long_numeric_ids")
    if (
        redact_long_numeric_ids_raw is None
        and "include_sensitive_ids" in runtime.logging_cfg
    ):
        redact_long_numeric_ids_raw = not bool(
            runtime.logging_cfg.get("include_sensitive_ids", True)
        )
    redact_long_numeric_ids = bool(redact_long_numeric_ids_raw)
    setup_logging(
        f"{datetime.now().strftime('%Y%m%d')}_intake_pear.log",
        log_dir=logs_root,
        level=level,
        fmt=str(runtime.logging_cfg.get("format", "text")),
        redact_long_numeric_ids=redact_long_numeric_ids,
        debug_http=_resolve_debug_http(
            verbose=args.verbose,
            logging_cfg=runtime.logging_cfg,
        ),
        timezone_name=runtime.run_cfg.get("timezone"),
    )
    validation_summary = ValidationSummary(tracked_rule_ids=all_rule_ids())
    pass_log = logging.info if args.verbose else None

    sharepoint_downloads: list[Path] = []
    sharepoint_source_keys: list[str] = []
    if args.download_from_sharepoint:
        sharepoint_settings = load_sharepoint_settings(runtime.config)
        sharepoint_source_keys = _resolve_pear_source_keys(
            config=runtime.config,
            requested_keys=args.sharepoint_source_key,
        )
        sharepoint_downloads = _download_sharepoint_sources(
            sharepoint_settings=sharepoint_settings,
            source_keys=sharepoint_source_keys,
            input_dir=input_dir,
            overwrite=args.overwrite_downloaded,
        )
        validation_summary.record_pass(
            rule_id=_RULE_PEAR_RUNTIME_CONFIG_ID,
            message=(
                "PEAR SharePoint source configuration resolved for intake: "
                + ", ".join(sharepoint_source_keys)
            ),
            log=pass_log,
        )
        if not sharepoint_downloads:
            validation_summary.record_warning(
                RuleResult(
                    rule_id=_RULE_PEAR_RUNTIME_CONFIG_ID,
                    code="pear_sharepoint_empty_download",
                    severity="warning",
                    message=(
                        "PEAR SharePoint download completed with zero XLSX files "
                        "for configured source keys"
                    ),
                ),
                log=logging.warning,
            )
        logging.info(
            "Downloaded %s PEAR XLSX file(s) from SharePoint source key(s): %s",
            len(sharepoint_downloads),
            ", ".join(sharepoint_source_keys),
        )

    files = discover_input_files(input_dir)
    if not files:
        print(f"No XLSX files found in {input_dir}")
        return 0

    if args.write_landing and not args.dry_run:
        ensure_dir(landing_output_dir)
    if args.write_processed and not args.dry_run:
        ensure_dir(processed_output_dir)

    reference = load_school_reference(reference_path)
    try:
        wave_windows = require_wave_window_authority(
            reference=reference,
            context="intake_pear transform pipeline",
            rule_id=RULE_PEAR_WAVE_WINDOW_AUTHORITY_ID,
        )
    except ValidationError as exc:
        validation_summary.record_failure(
            rule_id=RULE_PEAR_WAVE_WINDOW_AUTHORITY_ID,
            message=str(exc),
            log=logging.error,
        )
        print(
            "FAIL config "
            "error='school_reference is missing required suspension window metadata'"
        )
        return 1
    validation_summary.record_pass(
        rule_id=RULE_PEAR_WAVE_WINDOW_AUTHORITY_ID,
        message="school_reference wave-window metadata resolved for PEAR intake",
        log=pass_log,
    )
    adls_settings = None
    file_system_client: FileSystemClient | None = None
    landing_prefix: str | None = None
    processed_prefix: str | None = None
    if args.upload_to_adls:
        adls_settings = load_adls_settings(runtime.config)
        if args.write_landing:
            landing_prefix = _resolve_optional_prefix(
                configured=adls_settings.destinations.pear_landing_prefix,
                override=args.landing_prefix,
                label="io.adls.destinations.pear_landing_prefix",
            )
        if args.write_processed:
            processed_prefix = _resolve_optional_prefix(
                configured=adls_settings.destinations.pear_processed_prefix,
                override=args.processed_prefix,
                label="io.adls.destinations.pear_processed_prefix",
            )
        if not args.dry_run:
            file_system_client = get_file_system_client(adls_settings)

    collisions: dict[Path, Path] = {}
    processed_files: list[_ProcessedFile] = []
    failures = 0
    landing_extractor = (
        extract_canonical_landing_report
        if args.processed_only
        else extract_landing_report
    )
    if args.processed_only:
        logging.debug(
            "Processed-only mode: canonical landing workbooks are expected and footer diagnostics are skipped"
        )

    for file_index, source_file in enumerate(files, start=1):
        failure_rule_id = _RULE_PEAR_LANDING_SCHEMA_ID
        try:
            failure_rule_id = _RULE_PEAR_LANDING_SCHEMA_ID
            landing = landing_extractor(source_file)
            validate_landing_schema(
                landing,
                schema_root,
                strict_headers=runtime.strict_headers,
            )
            validation_summary.record_pass(
                rule_id=_RULE_PEAR_LANDING_SCHEMA_ID,
                message=f"PEAR landing schema passed for {source_file.name}",
                log=pass_log,
            )
            suspension_canonical_filename: str | None = None
            suspension_suffix: str | None = None
            suspension_suffix_warning: str | None = None
            if landing.report_type == REPORT_SUSPENSION:
                failure_rule_id = RULE_PEAR_SUSPENSION_SUFFIX_AUTHORITY_ID
                (
                    suspension_canonical_filename,
                    suspension_suffix,
                    suspension_suffix_warning,
                ) = resolve_suspension_canonical_filename(
                    landing,
                    reference=reference,
                )
                if suspension_suffix_warning:
                    validation_summary.record_warning(
                        RuleResult(
                            rule_id=RULE_PEAR_SUSPENSION_SUFFIX_AUTHORITY_ID,
                            code="pear_suspension_suffix_fallback_warning",
                            severity="warning",
                            message=(
                                f"{source_file.name}: {suspension_suffix_warning}"
                            ),
                        ),
                        log=logging.warning,
                    )
                else:
                    validation_summary.record_pass(
                        rule_id=RULE_PEAR_SUSPENSION_SUFFIX_AUTHORITY_ID,
                        message=(
                            f"Suspension canonical suffix resolved from school reference "
                            f"for {source_file.name}"
                        ),
                        log=pass_log,
                    )
            failure_rule_id = _RULE_PEAR_LANDING_SCHEMA_ID
            processed = None
            if not args.landing_only:
                failure_rule_id = _RULE_PEAR_PROCESSED_SCHEMA_ID
                processed = transform_report(
                    landing,
                    reference=reference,
                    wave_windows=wave_windows,
                )
                validate_processed_schema(
                    processed,
                    schema_root,
                    strict_headers=runtime.strict_headers,
                )
                validation_summary.record_pass(
                    rule_id=_RULE_PEAR_PROCESSED_SCHEMA_ID,
                    message=f"PEAR processed schema passed for {source_file.name}",
                    log=pass_log,
                )

            canonical_filename = (
                processed.canonical_filename
                if processed is not None
                else landing.canonical_filename
            )
            report_warnings = (
                processed.report_warnings if processed is not None else landing.warnings
            )
            if processed is None and landing.report_type == REPORT_SUSPENSION:
                assert suspension_canonical_filename is not None
                assert suspension_suffix is not None
                canonical_filename = suspension_canonical_filename
                warnings_list = list(report_warnings)
                if suspension_suffix_warning:
                    warnings_list.append(suspension_suffix_warning)
                if canonical_filename != landing.canonical_filename:
                    warnings_list.append(
                        "Suspension canonical filename suffix was derived from school reference "
                        f"levels ({suspension_suffix}) instead of title text"
                    )
                report_warnings = tuple(warnings_list)
            processed_rows = (
                processed.processed_frame.height if processed is not None else 0
            )
            no_action_rows = processed.no_action_count if processed is not None else 0

            landing_output: Path | None = None
            if args.write_landing:
                landing_output = landing_output_dir / canonical_filename
                previous_source = collisions.get(landing_output)
                if previous_source is not None and previous_source != source_file:
                    _warn_overwrite(landing_output, source_file)
                collisions[landing_output] = source_file
                if not args.dry_run:
                    landing.landing_frame.write_excel(landing_output)

            processed_output: Path | None = None
            processed_outputs: tuple[Path, ...] = ()
            if args.write_processed:
                if processed is None:
                    raise RuntimeError(
                        "Processed output requested but processed transform was skipped"
                    )
                partitions = _partition_processed_frame_by_wave(
                    frame=processed.processed_frame,
                    report_type=landing.report_type,
                    canonical_filename=canonical_filename,
                    reference=reference,
                    source_file=source_file,
                )
                written_processed_outputs: list[Path] = []
                for slice_token, scoped_frame in sorted(partitions.items()):
                    output_name = _processed_wave_filename(
                        report_date=landing.footer.report_date,
                        report_type=landing.report_type,
                        slice_token=slice_token,
                    )
                    output_path = processed_output_dir / output_name
                    previous_source = collisions.get(output_path)
                    if previous_source is not None and previous_source != source_file:
                        _warn_overwrite(output_path, source_file)
                    collisions[output_path] = source_file
                    if not args.dry_run:
                        scoped_frame.write_parquet(output_path)
                    written_processed_outputs.append(output_path)
                if written_processed_outputs:
                    processed_output = written_processed_outputs[0]
                    processed_outputs = tuple(written_processed_outputs)

            warning_count = len(report_warnings)
            processed_files.append(
                _ProcessedFile(
                    source_file=source_file,
                    report_type=landing.report_type,
                    report_date=landing.footer.report_date,
                    landing_output=landing_output,
                    processed_output=processed_output,
                    processed_outputs=processed_outputs,
                    landing_rows=landing.landing_frame.height,
                    processed_rows=processed_rows,
                    no_action_rows=no_action_rows,
                    warning_count=warning_count,
                    warnings=report_warnings,
                )
            )
            for warning in report_warnings:
                validation_summary.record_warning(
                    RuleResult(
                        rule_id=RULE_PARSE_DIAGNOSTICS_ID,
                        code="pear_report_warning",
                        severity="warning",
                        message=f"{source_file.name}: {warning}",
                    ),
                    log=logging.warning,
                )
            if args.verbose:
                print(
                    "PASS intake "
                    f"[{file_index}/{len(files)}] "
                    f"file={source_file.name!r} "
                    f"type={landing.report_type} "
                    f"landing_rows={landing.landing_frame.height} "
                    f"processed_rows={processed_rows} "
                    f"no_action_rows={no_action_rows} "
                    f"report_date={landing.footer.report_date.isoformat()} "
                    f"canonical={canonical_filename!r} "
                    f"warnings={warning_count}"
                )
        except (ValidationError, FileNotFoundError, ValueError) as exc:
            failures += 1
            validation_summary.record_failure(
                rule_id=failure_rule_id,
                message=f"PEAR intake failed for {source_file.name}: {exc}",
                log=logging.error,
            )
            print(f"FAIL intake file={source_file.name!r} error={exc}")
            if args.fail_fast:
                break

    processed_rescind_patch_summary: dict[str, int | list[str]] = {
        "rescind_action_rows": 0,
        "matched_rows": 0,
        "patched_rows": 0,
        "preserved_existing_rows": 0,
        "unmatched_action_rows": 0,
        "delete_action_rows": 0,
        "matched_delete_rows": 0,
        "unmatched_delete_action_rows": 0,
        "matched_delete_client_ids": [],
        "patched_files": 0,
    }
    if args.write_processed and not args.dry_run and not args.landing_only:
        processed_rescind_patch_summary = _patch_processed_suspension_rescinds(
            processed_files=processed_files,
        )
        if processed_rescind_patch_summary["patched_rows"]:
            logging.info(
                "Patched processed suspension rescind_date values from action queue: "
                "patched_rows=%s matched_rows=%s action_rows=%s patched_files=%s",
                processed_rescind_patch_summary["patched_rows"],
                processed_rescind_patch_summary["matched_rows"],
                processed_rescind_patch_summary["rescind_action_rows"],
                processed_rescind_patch_summary["patched_files"],
            )
    matched_delete_client_ids = processed_rescind_patch_summary.get(
        "matched_delete_client_ids", []
    )
    delete_match_warning = delete_action_match_warning(
        client_ids=[str(value) for value in matched_delete_client_ids]
        if isinstance(matched_delete_client_ids, list)
        else []
    )
    rescind_action_rows = (
        processed_rescind_patch_summary["rescind_action_rows"]
        if isinstance(processed_rescind_patch_summary["rescind_action_rows"], int)
        else 0
    )
    matched_delete_rows = (
        processed_rescind_patch_summary["matched_delete_rows"]
        if isinstance(processed_rescind_patch_summary["matched_delete_rows"], int)
        else 0
    )
    if delete_match_warning is not None:
        validation_summary.record_warning(delete_match_warning, log=logging.warning)
    else:
        validation_summary.record_pass(
            rule_id=RULE_PEAR_DELETE_ACTION_MATCH_ID,
            message="No delete action rows matched current suspension rows",
            log=pass_log,
        )

    written_paths, uploaded_paths = _write_outputs(
        processed_files=processed_files,
        dry_run=args.dry_run,
        upload_to_adls=args.upload_to_adls,
        file_system_client=file_system_client,
        landing_prefix=landing_prefix,
        processed_prefix=processed_prefix,
    )

    quality_dir = ensure_dir(artifacts_root / "data_quality")
    timestamp = datetime.now().strftime("%Y%m%dT%H%M%S")
    manifest_path = write_manifest(
        quality_dir=quality_dir,
        timestamp=timestamp,
        run_date=datetime.now().date(),
        mode="intake_pear",
        file_outputs=written_paths,
        extra={
            "status": "failed" if failures else "success",
            "input_dir": str(input_dir),
            "schema_root": str(schema_root),
            "reference_path": str(reference_path),
            "processed_file_count": len(processed_files),
            "failed_file_count": failures,
            "dry_run": args.dry_run,
            "landing_only": args.landing_only,
            "processed_only": args.processed_only,
            "upload_to_adls": args.upload_to_adls,
            "adls_landing_prefix": landing_prefix,
            "adls_processed_prefix": processed_prefix,
            "adls_uploaded_count": len(uploaded_paths),
            "download_from_sharepoint": args.download_from_sharepoint,
            "sharepoint_source_keys": sharepoint_source_keys,
            "sharepoint_downloaded_count": len(sharepoint_downloads),
            "processed_rescind_patch_summary": processed_rescind_patch_summary,
            "validation": validation_summary.as_dict(),
        },
    )

    total_warning_count = sum(entry.warning_count for entry in processed_files)
    print("PEAR intake complete")
    print("Summary:")
    print(f"  landing_only={args.landing_only}")
    print(f"  processed_only={args.processed_only}")
    print(f"  total_files={len(files)}")
    print(f"  processed={len(processed_files)}")
    print(f"  failed={failures}")
    print(f"  written={len(written_paths)}")
    print(f"  uploaded={len(uploaded_paths)}")
    if args.download_from_sharepoint:
        if args.verbose:
            print(
                "  "
                f"sharepoint_downloads={len(sharepoint_downloads)} "
                f"from {', '.join(sharepoint_source_keys)}"
            )
        else:
            print(f"  sharepoint_downloads={len(sharepoint_downloads)}")
    print("Warnings:")
    print(f"  intake_warning_count={total_warning_count}")
    if rescind_action_rows > 0:
        if args.verbose:
            print(
                "  processed_rescind_patch: "
                f"patched_rows={processed_rescind_patch_summary['patched_rows']} "
                f"matched_rows={processed_rescind_patch_summary['matched_rows']} "
                f"action_rows={processed_rescind_patch_summary['rescind_action_rows']} "
                "preserved_existing_rows="
                f"{processed_rescind_patch_summary['preserved_existing_rows']} "
                f"unmatched_action_rows={processed_rescind_patch_summary['unmatched_action_rows']} "
                f"patched_files={processed_rescind_patch_summary['patched_files']}"
            )
        else:
            print(
                "  processed_rescind_patch: "
                f"action_rows={processed_rescind_patch_summary['rescind_action_rows']} "
                f"patched_rows={processed_rescind_patch_summary['patched_rows']} "
                f"unmatched_action_rows={processed_rescind_patch_summary['unmatched_action_rows']}"
            )
    if matched_delete_rows > 0:
        print(
            "  delete_action_match_warning: "
            f"(matched_delete_rows={processed_rescind_patch_summary['matched_delete_rows']} "
            f"delete_action_rows={processed_rescind_patch_summary['delete_action_rows']})"
        )
    print("Validation:")
    print(
        "  status="
        f"{validation_summary.status} "
        f"(applied={validation_summary.applied}, "
        f"pass={validation_summary.passed}, "
        f"warn={validation_summary.warned}, "
        f"fail={validation_summary.failed})"
    )
    rule_counts = validation_summary.rule_status_counts()
    print(
        "  rules="
        f"PASS={rule_counts.get('PASS', 0)} "
        f"WARN={rule_counts.get('WARN', 0)} "
        f"FAIL={rule_counts.get('FAIL', 0)} "
        f"NONE={rule_counts.get('NONE', 0)}"
    )
    print("Artifacts:")
    print(f"  manifest={manifest_path if args.verbose else manifest_path.name}")
    if args.verbose and uploaded_paths:
        print(f"  uploaded_paths={len(uploaded_paths)}")
        for remote in uploaded_paths:
            print(f"    - {remote}")

    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
