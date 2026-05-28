from __future__ import annotations

import argparse
import logging
from datetime import datetime
from pathlib import Path

from ispa_daily_workflow.config import ensure_dir
from ispa_daily_workflow.io.adls import load_adls_settings
from ispa_daily_workflow.io.sharepoint_settings import load_sharepoint_settings
from ispa_daily_workflow.io.workdays import parse_run_date
from ispa_daily_workflow.logging import setup_logging
from ispa_daily_workflow.pipeline import extract_stage
from ispa_daily_workflow.pipeline.workflow_config import load_workflow_config
from ispa_daily_workflow.quality import write_manifest
from ispa_daily_workflow.reference import load_school_reference

PROJECT_ROOT = Path(__file__).resolve().parents[3]


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Extract raw Panorama inputs from SharePoint overdue drop folder into "
            "local input/raw and optionally upload to ADLS landing."
        )
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
        "--input-raw-dir",
        type=Path,
        default=None,
        help="Override local download target (default: config paths.input_raw).",
    )
    parser.add_argument(
        "--upload-to-adls",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Upload downloaded files to ADLS landing path.",
    )
    parser.add_argument(
        "--landing-prefix",
        type=str,
        default=None,
        help=(
            "ADLS destination prefix override. Default: "
            "<io.adls.destinations.landing_prefix>."
        ),
    )
    parser.add_argument(
        "--overwrite-local",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Overwrite local files if they already exist.",
    )
    parser.add_argument(
        "--debug-http",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Enable verbose request logging for Graph/ADLS HTTP clients.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable verbose logging.",
    )
    return parser.parse_args(argv)


def _resolve_debug_http(value: bool | None, logging_cfg: dict[str, object]) -> bool:
    default = bool(logging_cfg.get("debug_http_requests", False))
    if value is None:
        return default
    return bool(value)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    run_day = parse_run_date(args.run_date)
    run_date = run_day.strftime("%Y%m%d")

    runtime = load_workflow_config(args, project_root=PROJECT_ROOT)

    input_raw = args.input_raw_dir or runtime.required_path("input_raw")
    input_raw = ensure_dir(input_raw)
    schema_root = runtime.validation_path("schemas")
    reference_path = runtime.required_path("reference")
    runtime.validate_files(
        reference_path=reference_path,
    )

    logs_root = runtime.required_path("logs_root")
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
    debug_http = _resolve_debug_http(args.debug_http, runtime.logging_cfg)
    setup_logging(
        f"{run_date}_extract.log",
        log_dir=logs_root,
        level=level,
        fmt=str(runtime.logging_cfg.get("format", "text")),
        redact_long_numeric_ids=redact_long_numeric_ids,
        debug_http=debug_http,
        timezone_name=runtime.run_cfg.get("timezone"),
    )

    reference = load_school_reference(reference_path)
    sharepoint_settings = load_sharepoint_settings(runtime.config)
    adls_settings = load_adls_settings(runtime.config)

    run_error: Exception | None = None
    result = None
    try:
        result = extract_stage(
            run_day=run_day,
            run_date=run_date,
            input_raw=input_raw,
            schema_root=schema_root,
            reference=reference,
            sharepoint_settings=sharepoint_settings,
            adls_settings=adls_settings,
            upload_to_adls=args.upload_to_adls,
            strict_headers=runtime.strict_headers,
            landing_prefix=args.landing_prefix,
            overwrite_local=args.overwrite_local,
        )
    except Exception as exc:
        run_error = exc
        logging.exception("extract_inputs failed")

    artifacts_root = runtime.required_path("artifacts_root")
    quality_dir = ensure_dir(artifacts_root / "data_quality")
    timestamp = datetime.now().strftime("%Y%m%dT%H%M%S")
    renamed_outputs = result.renamed_outputs if result is not None else []
    adls_uploaded = result.adls_uploaded_paths if result is not None else []
    manifest_path = write_manifest(
        quality_dir=quality_dir,
        timestamp=timestamp,
        run_date=run_day,
        mode="extract_inputs",
        file_outputs=renamed_outputs,
        extra={
            "status": "failed" if run_error else "success",
            "created_timezone": "America/Toronto",
            "recursive": True,
            "max_subfolder_depth": 2,
            "created_window_start_utc": (
                result.created_window_start_utc if result is not None else None
            ),
            "created_window_end_utc": (
                result.created_window_end_utc if result is not None else None
            ),
            "enumerated_count": result.enumerated_count if result is not None else 0,
            "non_file_skipped_count": (
                result.non_file_skipped_count if result is not None else 0
            ),
            "rejected_by_suffix_count": (
                result.rejected_by_suffix_count if result is not None else 0
            ),
            "rejected_by_date_count": (
                result.rejected_by_date_count if result is not None else 0
            ),
            "in_window_count": result.selected_count if result is not None else 0,
            "downloaded_count": result.selected_count if result is not None else 0,
            "renamed_count": len(renamed_outputs),
            "adls_uploaded_count": len(adls_uploaded),
            "adls_upload_enabled": args.upload_to_adls,
            "adls_landing_prefix": adls_uploaded[0].rsplit("/", 1)[0]
            if adls_uploaded
            else None,
            "input_raw_dir": str(input_raw),
            "error_type": type(run_error).__name__ if run_error else None,
            "error_message": str(run_error) if run_error else None,
        },
    )

    print(f"Selected files: {result.selected_count if result is not None else 0}")
    print(f"Renamed files: {len(renamed_outputs)}")
    if renamed_outputs:
        for path in renamed_outputs:
            print(f"  - {path}")
    print(f"ADLS uploads: {len(adls_uploaded)}")
    if adls_uploaded:
        for remote in adls_uploaded:
            print(f"  - {remote}")
    print(f"Manifest: {manifest_path}")

    if run_error:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
