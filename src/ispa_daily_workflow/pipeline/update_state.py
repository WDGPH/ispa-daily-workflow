from __future__ import annotations

import argparse
import logging
import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]

from ispa_daily_workflow.compliance_history import (
    discover_latest_compliance_history_by_slice,
)
from ispa_daily_workflow.config import ensure_dir
from ispa_daily_workflow.io.adls import (
    PEAR_LANDING_CANONICAL_FILENAME_PATTERN,
    download_files_for_date,
    load_adls_settings,
    upload_paths,
)
from ispa_daily_workflow.io.sharepoint_settings import load_sharepoint_settings
from ispa_daily_workflow.io.workdays import parse_run_date
from ispa_daily_workflow.logging import setup_logging
from ispa_daily_workflow.pipeline import RunDayOptions, run_day
from ispa_daily_workflow.pipeline.delivery_runtime import IOMode
from ispa_daily_workflow.pipeline.workflow_config import load_workflow_config
from ispa_daily_workflow.progress import configure_progress
from ispa_daily_workflow.reference import collect_scope_values, load_school_reference
from ispa_daily_workflow.validation.scope import (
    normalize_level_scope_value,
    normalize_school_scope_value,
    normalize_wave_scope_value,
)

PEAR_SHAREPOINT_SOURCE_KEYS = (
    "inputs.pear_overdue",
    "inputs.pear_suspension_vs_overdue",
    "inputs.pear_suspension",
)
SOURCE_CHOICES = ("panorama", "pear")


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Update authoritative state for one source. "
            "Use --source panorama for compliance_history updates or --source pear "
            "for PEAR intake/state derivation."
        )
    )
    parser.add_argument(
        "--source",
        required=True,
        choices=SOURCE_CHOICES,
        help="Required source selector: panorama or pear.",
    )
    parser.add_argument(
        "--run-date",
        type=str,
        default=None,
        help="Run date in YYYYMMDD format (default: today).",
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
        help="Preview state-update execution with no writes/uploads/deletes.",
    )
    parser.add_argument(
        "--init-compliance-history",
        action="store_true",
        help=(
            "Panorama only: allow first-time compliance_history bootstrap when no "
            "prior snapshot exists."
        ),
    )
    parser.add_argument(
        "--allow-new-client-ids",
        action="store_true",
        help="Panorama only: allow new client_id additions during compliance_history update.",
    )
    scope_group = parser.add_mutually_exclusive_group(required=False)
    scope_group.add_argument(
        "--wave",
        type=str,
        default=None,
        help=(
            "Filter processing to one wave from school_reference (or ALL). "
            "Required with --init-compliance-history."
        ),
    )
    scope_group.add_argument(
        "--level",
        type=str,
        default=None,
        help="Filter processing to one level from school_reference (or ALL).",
    )
    scope_group.add_argument(
        "--school",
        type=str,
        default=None,
        help="Filter processing to one school ID (digits only) or ALL.",
    )
    parser.add_argument(
        "--retain-local-scratch",
        action="store_true",
        help=(
            "Keep local scratch files for the selected source. "
            "Panorama: input/raw + input/renamed; pear: run-scoped scratch."
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
        "--derive-state",
        action=argparse.BooleanOptionalAction,
        default=None,
        help=(
            "PEAR only: derive PEAR state artifacts after processed intake "
            "(default: enabled for --source pear)."
        ),
    )
    parser.add_argument(
        "--sharepoint-source-key",
        action="append",
        choices=PEAR_SHAREPOINT_SOURCE_KEYS,
        default=None,
        help=(
            "PEAR only: optional SharePoint source key override; can be repeated. "
            "Default uses all configured PEAR source keys."
        ),
    )
    parser.add_argument(
        "--input-dir",
        type=Path,
        default=None,
        help="PEAR only: intake input dir override (default: run-scoped scratch).",
    )
    parser.add_argument(
        "--landing-output-dir",
        type=Path,
        default=None,
        help=(
            "PEAR only: landing output dir override "
            "(default: <paths.input_root>/state_sync/<run_date>/pear/landing)."
        ),
    )
    parser.add_argument(
        "--processed-output-dir",
        type=Path,
        default=None,
        help=(
            "PEAR only: processed output dir override "
            "(default: <paths.output_root>/pear_processed)."
        ),
    )
    parser.add_argument(
        "--state-output-dir",
        type=Path,
        default=None,
        help=(
            "PEAR only: state output dir override "
            "(default: <paths.output_root>/pear_state)."
        ),
    )
    parser.add_argument(
        "--authoritative-output-dir",
        type=Path,
        default=None,
        help=(
            "PEAR only: authoritative suspension_operational baseline output dir "
            "override (default: <paths.output_root>/pear_processed)."
        ),
    )
    args = parser.parse_args(argv)

    selected_scope = [
        value for value in (args.wave, args.level, args.school) if value is not None
    ]
    if any(not str(value).strip() for value in selected_scope):
        parser.error("--wave/--level/--school require non-empty values")
    if args.school is not None:
        try:
            normalized_school, _ = normalize_school_scope_value(args.school)
        except ValueError as exc:
            parser.error(str(exc))
        args.school = normalized_school

    if args.source == "panorama":
        if args.allow_new_client_ids and len(selected_scope) != 1:
            parser.error(
                "--allow-new-client-ids requires exactly one scope flag: "
                "--wave, --level, or --school"
            )
        if args.init_compliance_history and args.wave is None:
            parser.error("--init-compliance-history requires --wave")
        if args.derive_state is not None:
            parser.error("--derive-state is only valid with --source pear")
        if args.sharepoint_source_key:
            parser.error("--sharepoint-source-key is only valid with --source pear")
        if args.input_dir:
            parser.error("--input-dir is only valid with --source pear")
        if args.landing_output_dir:
            parser.error("--landing-output-dir is only valid with --source pear")
        if args.processed_output_dir:
            parser.error("--processed-output-dir is only valid with --source pear")
        if args.state_output_dir:
            parser.error("--state-output-dir is only valid with --source pear")
        if args.authoritative_output_dir:
            parser.error("--authoritative-output-dir is only valid with --source pear")
    else:
        if selected_scope:
            parser.error(
                "--wave/--level/--school are only valid with --source panorama"
            )
        if args.init_compliance_history:
            parser.error(
                "--init-compliance-history is only valid with --source panorama"
            )
        if args.allow_new_client_ids:
            parser.error("--allow-new-client-ids is only valid with --source panorama")
    return args


def _resolve_debug_http(*, verbose: bool, logging_cfg: dict[str, object]) -> bool:
    return verbose or bool(logging_cfg.get("debug_http_requests", False))


def _build_pear_intake_command(
    *,
    config_path: Path,
    input_dir: Path,
    landing_output_dir: Path | None,
    processed_output_dir: Path | None,
    sharepoint_source_keys: list[str],
    download_from_sharepoint: bool,
    upload_to_adls: bool,
    landing_only: bool,
    processed_only: bool,
    verbose: bool,
) -> list[str]:
    command = [
        sys.executable,
        "-m",
        "ispa_daily_workflow.pipeline.intake_pear",
        "--config",
        str(config_path),
        "--input-dir",
        str(input_dir),
    ]
    if download_from_sharepoint:
        command.append("--download-from-sharepoint")
    if upload_to_adls:
        command.append("--upload-to-adls")
    if landing_only:
        command.append("--landing-only")
    if processed_only:
        command.append("--processed-only")
    if landing_output_dir is not None:
        command.extend(["--landing-output-dir", str(landing_output_dir)])
    if processed_output_dir is not None:
        command.extend(["--processed-output-dir", str(processed_output_dir)])
    for source_key in sharepoint_source_keys:
        command.extend(["--sharepoint-source-key", source_key])
    if verbose:
        command.append("--verbose")
    return command


def _clear_directory_files(directory: Path) -> int:
    if not directory.exists():
        return 0
    removed = 0
    for path in directory.iterdir():
        if path.is_file() and path.suffix.lower() in {".xlsx", ".xls"}:
            path.unlink()
            removed += 1
    return removed


def _cleanup_pear_scratch(
    *,
    scratch_root: Path,
    pear_input_dir: Path,
    pear_landing_dir: Path,
    use_default_scratch: bool,
) -> None:
    if use_default_scratch:
        if scratch_root.exists():
            shutil.rmtree(scratch_root, ignore_errors=True)
        return
    _clear_directory_files(pear_input_dir)
    _clear_directory_files(pear_landing_dir)


def _build_pear_state_command(
    *,
    config_path: Path,
    run_date: str,
    processed_dir: Path,
    output_dir: Path,
    authoritative_output_dir: Path,
    verbose: bool,
) -> list[str]:
    command = [
        sys.executable,
        "-m",
        "ispa_daily_workflow.pipeline.derive_pear_state",
        "--config",
        str(config_path),
        "--run-date",
        run_date,
        "--processed-dir",
        str(processed_dir),
        "--output-dir",
        str(output_dir),
        "--authoritative-output-dir",
        str(authoritative_output_dir),
    ]
    if verbose:
        command.append("--verbose")
    return command


def _resolve_pear_paths(
    *,
    args: argparse.Namespace,
    input_root: Path,
    output_root: Path,
    run_date: str,
) -> tuple[Path, Path, Path, Path, Path, Path, bool]:
    scratch_root = input_root / "state_sync" / run_date / "pear"
    input_dir = args.input_dir or (scratch_root / "raw")
    landing_output_dir = args.landing_output_dir or (scratch_root / "landing")
    processed_output_dir = args.processed_output_dir or (output_root / "pear_processed")
    state_output_dir = args.state_output_dir or (output_root / "pear_state")
    authoritative_output_dir = args.authoritative_output_dir or processed_output_dir
    use_default_scratch = args.input_dir is None and args.landing_output_dir is None
    return (
        scratch_root,
        input_dir,
        landing_output_dir,
        processed_output_dir,
        state_output_dir,
        authoritative_output_dir,
        use_default_scratch,
    )


def _run_child_command(*, command: list[str], label: str) -> None:
    logging.info("Stage: %s", label)
    logging.debug(
        "%s command: %s",
        label,
        " ".join(shlex.quote(token) for token in command),
    )
    env = os.environ.copy()
    src_path = str(PROJECT_ROOT / "src")
    pythonpath = env.get("PYTHONPATH")
    env["PYTHONPATH"] = (
        src_path if not pythonpath else os.pathsep.join([src_path, pythonpath])
    )
    completed = subprocess.run(command, cwd=PROJECT_ROOT, env=env, check=False)
    if completed.returncode != 0:
        raise RuntimeError(f"{label} failed with exit code {completed.returncode}")
    logging.debug("Completed %s", label)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    io_mode = IOMode.for_update(dry_run=args.dry_run)
    configure_progress(args.progress)
    run_day_value = parse_run_date(args.run_date)
    run_date = run_day_value.strftime("%Y%m%d")

    runtime = load_workflow_config(args, project_root=PROJECT_ROOT)
    config_path = runtime.config_path

    input_root = runtime.required_path("input_root")
    input_raw = runtime.required_path("input_raw")
    standardized_root = runtime.required_path("input_renamed")
    standardized_dir = standardized_root / run_date

    output_root = runtime.required_path("output_root")
    combined_dir = output_root / "combined"
    compliance_history_dir = output_root / "compliance_history"
    diff_dir = output_root / "diffs"
    reports_dir = output_root / "reports"

    artifacts_root = runtime.required_path("artifacts_root")

    logs_root = runtime.required_path("logs_root")
    schema_root = runtime.validation_path("schemas")
    reference_path = runtime.required_path("reference")
    workdays_path: Path | None = None
    if args.source == "panorama":
        workdays_path = runtime.run_path("workdays_csv")

    runtime.validate_files(
        reference_path=reference_path,
        workdays_path=workdays_path,
        require_workdays=args.source == "panorama",
    )

    reference = None
    if args.source == "panorama":
        reference = load_school_reference(reference_path)
        allowed_waves, allowed_levels = collect_scope_values(reference)
        try:
            if args.wave is not None:
                args.wave, _ = normalize_wave_scope_value(
                    args.wave,
                    allowed_values=allowed_waves,
                )
            if args.level is not None:
                args.level, _ = normalize_level_scope_value(
                    args.level,
                    allowed_values=allowed_levels,
                )
        except ValueError as exc:
            print(str(exc))
            return 2

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
    log_path = setup_logging(
        None if args.dry_run else f"{run_date}_update_state.log",
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

    if io_mode.dry_run:
        print("Dry run: update_state")
        print("No writes/uploads/deletes will be performed.")
        print(f"Mode: {io_mode.label}")
        print(f"Source: {args.source}")
        print(f"Run date: {run_date}")
        print(f"Config: {config_path}")
        if args.source == "panorama":
            local_compliance_histories = discover_latest_compliance_history_by_slice(
                compliance_history_dir, run_date=run_date
            )
            print(f"Input raw dir: {input_raw}")
            print(f"Compliance History dir: {compliance_history_dir}")
            if args.wave is not None:
                print(f"Scope wave: {args.wave}")
            if args.level is not None:
                print(f"Scope level: {args.level}")
            if args.school is not None:
                print(f"Scope school: {args.school}")
            print(f"Retain local scratch: {args.retain_local_scratch}")
            print(
                f"Local compliance_history slices available: {len(local_compliance_histories)}"
            )
            if local_compliance_histories:
                for slice_token, path in sorted(local_compliance_histories.items()):
                    print(f"  - {slice_token}: {path.name}")
        else:
            (
                _scratch_root,
                pear_input_dir,
                pear_landing_output_dir,
                pear_processed_output_dir,
                pear_state_output_dir,
                pear_authoritative_output_dir,
                _use_default_scratch,
            ) = _resolve_pear_paths(
                args=args,
                input_root=input_root,
                output_root=output_root,
                run_date=run_date,
            )
            derive_state_enabled = (
                True if args.derive_state is None else args.derive_state
            )
            source_keys_display = (
                ", ".join(args.sharepoint_source_key)
                if args.sharepoint_source_key
                else "(all configured)"
            )
            print(f"SharePoint source keys: {source_keys_display}")
            print(f"Input dir: {pear_input_dir}")
            print(f"Landing dir: {pear_landing_output_dir}")
            print(f"Processed dir: {pear_processed_output_dir}")
            print(f"State derivation: {derive_state_enabled}")
            if derive_state_enabled:
                print(f"State dir: {pear_state_output_dir}")
                print(
                    "Authoritative suspension-operational dir: "
                    f"{pear_authoritative_output_dir}"
                )
            print(f"Retain local scratch: {args.retain_local_scratch}")
        return 0

    logging.info("Starting update_state for %s source=%s", run_date, args.source)
    ensure_dir(input_root)
    ensure_dir(artifacts_root)

    if args.source == "panorama":
        ensure_dir(input_raw)
        ensure_dir(standardized_root)
        ensure_dir(combined_dir)
        ensure_dir(compliance_history_dir)
        ensure_dir(diff_dir)
        ensure_dir(reports_dir)
        assert reference is not None
        adls_settings = load_adls_settings(runtime.config)
        sharepoint_settings = load_sharepoint_settings(runtime.config)
        assert workdays_path is not None

        logo_path = runtime.logo_path()
        privacy_notice_path = runtime.privacy_notice_path()
        typst_bin = runtime.typst_bin()

        options = RunDayOptions(
            derive_diff_enabled=False,
            derive_overdue_report_enabled=False,
            derive_suspension_report_enabled=False,
            sharepoint_extract_inputs_enabled=True,
            adls_download_inputs_enabled=True,
            adls_sync_compliance_history_enabled=True,
            adls_upload_compliance_history_enabled=True,
            adls_upload_combined_enabled=False,
            adls_upload_diff_enabled=False,
            sharepoint_publish_diff_enabled=False,
            sharepoint_publish_overdue_pdf_enabled=False,
            sharepoint_publish_suspension_pdf_enabled=False,
            sharepoint_cleanup_pdfs_enabled=False,
            retain_local_inputs=args.retain_local_scratch,
            allow_compliance_history_additions=args.allow_new_client_ids,
            allow_compliance_history_bootstrap=args.init_compliance_history,
            keep_typst_artifacts=False,
            strict_headers=runtime.strict_headers,
            prune_history=False,
            no_compile=False,
            verbose=args.verbose,
            expected_input_count=None,
            school_ids=[args.school] if args.school is not None else [],
            levels=[args.level] if args.level is not None else [],
            waves=[args.wave] if args.wave is not None else [],
            extract_upload_to_adls=True,
        )

        result = run_day(
            run_day=run_day_value,
            run_date=run_date,
            project_root=PROJECT_ROOT,
            input_raw=input_raw,
            standardized_dir=standardized_dir,
            combined_dir=combined_dir,
            compliance_history_dir=compliance_history_dir,
            diff_dir=diff_dir,
            reports_dir=reports_dir,
            artifacts_root=artifacts_root,
            schema_root=schema_root,
            workdays_path=workdays_path,
            reference=reference,
            adls_settings=adls_settings,
            sharepoint_settings=sharepoint_settings,
            outputs_cfg=runtime.outputs_cfg,
            alerts_cfg=runtime.alerts_cfg,
            options=options,
            logo_path=logo_path,
            typst_bin=typst_bin,
            school_year_start_month=runtime.school_year_start_month,
            privacy_notice_path=privacy_notice_path,
            log_path=log_path,
        )

        print(f"Status: {result.status}")
        print(f"Warnings: {result.warning_count}")
        print(f"Errors: {result.error_count}")
        validation = result.stages.get("process", {}).get("validation")
        if isinstance(validation, dict):
            print(
                "Validation: "
                f"{validation.get('status', 'NONE')} "
                f"(applied={validation.get('applied', 0)}, "
                f"pass={validation.get('passed', 0)}, "
                f"warn={validation.get('warned', 0)}, "
                f"fail={validation.get('failed', 0)})"
            )
            rule_counts = validation.get("rule_status_counts", {})
            if isinstance(rule_counts, dict):
                print(
                    "Validation rules: "
                    f"PASS={rule_counts.get('PASS', 0)} "
                    f"WARN={rule_counts.get('WARN', 0)} "
                    f"FAIL={rule_counts.get('FAIL', 0)} "
                    f"NONE={rule_counts.get('NONE', 0)}"
                )
        print(f"Run artifact: {result.run_artifact_path}")
        if result.critical_messages:
            print("Critical messages:")
            for message in result.critical_messages[:10]:
                print(f"  - {message}")

        return 0 if result.status == "success" else 1

    adls_settings = load_adls_settings(runtime.config)
    (
        pear_scratch_root,
        pear_input_dir,
        pear_landing_output_dir,
        pear_processed_output_dir,
        pear_state_output_dir,
        pear_authoritative_output_dir,
        use_default_pear_scratch,
    ) = _resolve_pear_paths(
        args=args,
        input_root=input_root,
        output_root=output_root,
        run_date=run_date,
    )
    sharepoint_source_keys = args.sharepoint_source_key or []
    derive_state_enabled = True if args.derive_state is None else args.derive_state
    pear_landing_prefix = adls_settings.destinations.pear_landing_prefix
    if pear_landing_prefix is None or not pear_landing_prefix.strip():
        print(
            "PEAR state update failed: io.adls.destinations.pear_landing_prefix is "
            "required for PEAR landing re-download."
        )
        return 1

    downloaded_landing_count = 0
    try:
        ensure_dir(pear_input_dir)
        ensure_dir(pear_landing_output_dir)
        ensure_dir(pear_processed_output_dir)
        ensure_dir(pear_authoritative_output_dir)
        stale_input_removed = _clear_directory_files(pear_input_dir)
        stale_landing_removed = _clear_directory_files(pear_landing_output_dir)
        if stale_input_removed or stale_landing_removed:
            logging.debug(
                "Cleared stale PEAR scratch files before update: input=%s landing=%s",
                stale_input_removed,
                stale_landing_removed,
            )

        landing_command = _build_pear_intake_command(
            config_path=config_path,
            input_dir=pear_input_dir,
            landing_output_dir=pear_landing_output_dir,
            processed_output_dir=pear_processed_output_dir,
            sharepoint_source_keys=sharepoint_source_keys,
            download_from_sharepoint=True,
            upload_to_adls=True,
            landing_only=True,
            processed_only=False,
            verbose=args.verbose,
        )
        _run_child_command(command=landing_command, label="PEAR landing intake")

        _clear_directory_files(pear_landing_output_dir)
        downloaded_landing = download_files_for_date(
            adls_settings,
            run_date=run_date,
            output_dir=pear_landing_output_dir,
            prefix=pear_landing_prefix,
            filename_pattern=PEAR_LANDING_CANONICAL_FILENAME_PATTERN,
        )
        downloaded_landing_count = len(downloaded_landing)
        if not downloaded_landing:
            raise RuntimeError(
                "No PEAR landing files were re-downloaded from ADLS for run_date="
                f"{run_date} using prefix={pear_landing_prefix}"
            )

        processed_command = _build_pear_intake_command(
            config_path=config_path,
            input_dir=pear_landing_output_dir,
            landing_output_dir=pear_landing_output_dir,
            processed_output_dir=pear_processed_output_dir,
            sharepoint_source_keys=[],
            download_from_sharepoint=False,
            upload_to_adls=True,
            landing_only=False,
            processed_only=True,
            verbose=args.verbose,
        )
        _run_child_command(command=processed_command, label="PEAR processed intake")

        if derive_state_enabled:
            derive_command = _build_pear_state_command(
                config_path=config_path,
                run_date=run_date,
                processed_dir=pear_processed_output_dir,
                output_dir=pear_state_output_dir,
                authoritative_output_dir=pear_authoritative_output_dir,
                verbose=args.verbose,
            )
            _run_child_command(command=derive_command, label="PEAR state derivation")
            authoritative_paths = sorted(
                pear_authoritative_output_dir.glob(
                    f"{run_date}_pear_suspension_operational_*.parquet"
                )
            )
            if authoritative_paths:
                pear_processed_prefix = adls_settings.destinations.pear_processed_prefix
                if pear_processed_prefix is None or not pear_processed_prefix.strip():
                    raise RuntimeError(
                        "io.adls.destinations.pear_processed_prefix is required "
                        "to upload PEAR suspension_operational baseline artifacts"
                    )
                upload_paths(
                    adls_settings,
                    paths=authoritative_paths,
                    prefix=pear_processed_prefix,
                )

        source_keys_display = (
            ", ".join(sharepoint_source_keys)
            if sharepoint_source_keys
            else "(all configured)"
        )
        print("PEAR state update complete")
        print("Summary:")
        print(f"  PEAR source keys: {source_keys_display}")
        print(f"  PEAR landing re-downloaded: {downloaded_landing_count}")
        print(f"  PEAR state derivation: {derive_state_enabled}")
        print("Artifacts:")
        print(f"  PEAR processed dir: {pear_processed_output_dir}")
        if derive_state_enabled:
            print(f"  PEAR state dir: {pear_state_output_dir}")
            print(
                "  PEAR authoritative suspension-operational dir: "
                f"{pear_authoritative_output_dir}"
            )
    except Exception as exc:  # noqa: BLE001 - CLI boundary reports stage failure
        logging.error("PEAR state update failed: %s", exc)
        print(f"PEAR state update failed: {exc}")
        return 1
    finally:
        if not args.retain_local_scratch:
            _cleanup_pear_scratch(
                scratch_root=pear_scratch_root,
                pear_input_dir=pear_input_dir,
                pear_landing_dir=pear_landing_output_dir,
                use_default_scratch=use_default_pear_scratch,
            )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
