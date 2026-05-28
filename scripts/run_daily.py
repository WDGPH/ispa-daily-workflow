#!/usr/bin/env python3
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path
from typing import TypedDict

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_ROOT))

from panorama_compliance.config import ensure_dir
from panorama_compliance.io.adls import load_adls_settings
from panorama_compliance.io.sharepoint_settings import load_sharepoint_settings
from panorama_compliance.io.workdays import parse_run_date
from panorama_compliance.logging import setup_logging
from panorama_compliance.pipeline import RunDayOptions, run_day
from panorama_compliance.pipeline.workflow_config import load_workflow_config
from panorama_compliance.reference import load_school_reference

DERIVE_CHOICES = (
    "diff",
    "overdue_report",
    "suspension_report",
)
PUBLISH_CHOICES = (
    "diff",
    "overdue_pdf",
    "suspension_pdf",
)


class _ExecutionPlan(TypedDict):
    extract_inputs: bool
    download_inputs: bool
    sync_compliance_history: bool
    upload_landing: bool
    upload_compliance_history: bool
    upload_combined: bool
    upload_diff: bool
    derive: set[str]
    publish: set[str]
    cleanup_sharepoint_pdfs: bool


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run integrated daily panorama-compliance pipeline: "
            "SharePoint extract -> ADLS download -> compliance_history-driven outputs."
        )
    )
    parser.add_argument(
        "--mode",
        choices=("core", "full"),
        default="core",
        help=(
            "Execution preset. core=ingest+download+compliance_history only; "
            "full=core plus all derivations and ADLS derived uploads."
        ),
    )
    parser.add_argument(
        "--run-date", type=str, default=None, help="Run date in YYYYMMDD format."
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("profile/config.yaml"),
        help="Path to config file (default: ./profile/config.yaml).",
    )
    parser.add_argument(
        "--school-id", action="append", default=[], help="Filter school IDs."
    )
    parser.add_argument(
        "--level", action="append", default=[], help="Filter school levels."
    )
    parser.add_argument("--wave", action="append", default=[], help="Filter waves.")
    parser.add_argument(
        "--standardized-dir",
        type=Path,
        default=None,
        help="Override renamed directory.",
    )
    parser.add_argument(
        "--derive",
        action="append",
        default=[],
        choices=DERIVE_CHOICES,
        help=(
            "Enable derived outputs for this run; repeat as needed. "
            f"Choices: {', '.join(DERIVE_CHOICES)}."
        ),
    )
    parser.add_argument(
        "--publish",
        action="append",
        default=[],
        choices=PUBLISH_CHOICES,
        help=(
            "Enable SharePoint publish outputs for this run; repeat as needed. "
            f"Choices: {', '.join(PUBLISH_CHOICES)}."
        ),
    )
    parser.add_argument(
        "--extract-inputs",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Extract raw inputs from SharePoint overdue drop before ADLS download.",
    )
    parser.add_argument(
        "--download-inputs",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Download run-date raw inputs from ADLS landing.",
    )
    parser.add_argument(
        "--sync-compliance-history",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Sync latest prior compliance_history snapshots from ADLS before update.",
    )
    parser.add_argument(
        "--upload-landing",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Upload extracted canonical raw files to ADLS landing.",
    )
    parser.add_argument(
        "--upload-compliance-history",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Upload compliance_history parquet outputs to ADLS processed prefix.",
    )
    parser.add_argument(
        "--upload-combined",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Upload combined parquet outputs to ADLS processed prefix.",
    )
    parser.add_argument(
        "--upload-diff",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Upload diff parquet outputs to ADLS processed prefix.",
    )
    parser.add_argument(
        "--cleanup-sharepoint-pdfs",
        action=argparse.BooleanOptionalAction,
        default=None,
        help=(
            "Delete existing report PDFs in target SharePoint school folders before upload "
            "(case-insensitive; folder-scoped cleanup of overdue and suspension list files)."
        ),
    )
    parser.add_argument(
        "--retain-local-inputs",
        action="store_true",
        help="Keep raw/renamed inputs after run.",
    )
    parser.add_argument(
        "--allow-compliance-history-additions",
        action="store_true",
        help="Allow new client_id values to be added to compliance_history (default hard-fails).",
    )
    parser.add_argument(
        "--allow-compliance-history-bootstrap",
        action="store_true",
        help=(
            "Allow compliance_history initialization when no prior snapshot is available; "
            "use only for intentional bootstrap runs."
        ),
    )
    parser.add_argument(
        "--keep-typst-artifacts", action="store_true", help="Keep typst artifacts."
    )
    parser.add_argument(
        "--prune-history",
        action="store_true",
        help="Delete old PDFs before writing new ones.",
    )
    parser.add_argument(
        "--no-compile",
        action="store_true",
        help="Write Typst only, skip PDF compilation.",
    )
    parser.add_argument(
        "--expected-input-count",
        type=int,
        default=None,
        help="Expected file count for alerts.",
    )
    parser.add_argument(
        "--debug-http",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Enable verbose request logging for Graph/ADLS HTTP clients.",
    )
    parser.add_argument("--verbose", action="store_true", help="Verbose logging.")
    return parser.parse_args(argv)


def _resolve_bool_override(value: bool | None, default: bool) -> bool:
    if value is None:
        return default
    return bool(value)


def _resolve_debug_http(value: bool | None, logging_cfg: dict[str, object]) -> bool:
    default = bool(logging_cfg.get("debug_http_requests", False))
    if value is None:
        return default
    return bool(value)


def _resolve_mode_defaults(mode: str) -> _ExecutionPlan:
    if mode == "full":
        return {
            "extract_inputs": True,
            "download_inputs": True,
            "sync_compliance_history": True,
            "upload_landing": True,
            "upload_compliance_history": True,
            "upload_combined": True,
            "upload_diff": True,
            "derive": set(DERIVE_CHOICES),
            "publish": set(),
            "cleanup_sharepoint_pdfs": False,
        }
    return {
        "extract_inputs": True,
        "download_inputs": True,
        "sync_compliance_history": True,
        "upload_landing": True,
        "upload_compliance_history": True,
        "upload_combined": False,
        "upload_diff": False,
        "derive": set(),
        "publish": set(),
        "cleanup_sharepoint_pdfs": False,
    }


def _resolve_execution_plan(args: argparse.Namespace) -> _ExecutionPlan:
    defaults = _resolve_mode_defaults(args.mode)
    derive = set(defaults["derive"]) | {str(value) for value in args.derive}
    publish = set(defaults["publish"]) | {str(value) for value in args.publish}
    plan: _ExecutionPlan = {
        "extract_inputs": _resolve_bool_override(
            args.extract_inputs, bool(defaults["extract_inputs"])
        ),
        "download_inputs": _resolve_bool_override(
            args.download_inputs, bool(defaults["download_inputs"])
        ),
        "sync_compliance_history": _resolve_bool_override(
            args.sync_compliance_history, bool(defaults["sync_compliance_history"])
        ),
        "upload_landing": _resolve_bool_override(
            args.upload_landing, bool(defaults["upload_landing"])
        ),
        "upload_compliance_history": _resolve_bool_override(
            args.upload_compliance_history, bool(defaults["upload_compliance_history"])
        ),
        "upload_combined": _resolve_bool_override(
            args.upload_combined, bool(defaults["upload_combined"])
        ),
        "upload_diff": _resolve_bool_override(
            args.upload_diff, bool(defaults["upload_diff"])
        ),
        "derive": derive,
        "publish": publish,
        "cleanup_sharepoint_pdfs": _resolve_bool_override(
            args.cleanup_sharepoint_pdfs, bool(defaults["cleanup_sharepoint_pdfs"])
        ),
    }

    publish_requires_derive = {
        "diff": "diff",
        "overdue_pdf": "overdue_report",
        "suspension_pdf": "suspension_report",
    }
    missing_dependencies = [
        (publish_token, required)
        for publish_token, required in publish_requires_derive.items()
        if publish_token in publish and required not in derive
    ]
    if missing_dependencies:
        requirement_lines = ", ".join(
            f"{publish_token}->{required}"
            for publish_token, required in missing_dependencies
        )
        raise ValueError(
            "Publish selections require matching derive selections: "
            f"{requirement_lines}"
        )

    if plan["cleanup_sharepoint_pdfs"] and not (
        {"overdue_pdf", "suspension_pdf"} & publish
    ):
        raise ValueError(
            "--cleanup-sharepoint-pdfs requires --publish overdue_pdf or --publish suspension_pdf"
        )
    return plan


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    run_day_value = parse_run_date(args.run_date)
    run_date = run_day_value.strftime("%Y%m%d")

    runtime = load_workflow_config(args, project_root=PROJECT_ROOT)
    plan = _resolve_execution_plan(args)
    derive = set(plan["derive"])
    publish = set(plan["publish"])

    input_root = runtime.required_path("input_root")
    input_raw = runtime.required_path("input_raw")
    standardized_root = runtime.required_path("input_renamed")
    standardized_dir = args.standardized_dir or (standardized_root / run_date)

    output_root = runtime.required_path("output_root")
    combined_dir = ensure_dir(output_root / "combined")
    compliance_history_dir = ensure_dir(output_root / "compliance_history")
    diff_dir = ensure_dir(output_root / "diffs")
    reports_dir = ensure_dir(output_root / "reports")

    artifacts_root = runtime.required_path("artifacts_root")
    ensure_dir(artifacts_root)

    logs_root = runtime.required_path("logs_root")
    schema_root = runtime.validation_path("schemas")
    reference_path = runtime.required_path("reference")
    workdays_path = runtime.run_path("workdays_csv")
    logo_path = runtime.logo_path()
    privacy_notice_path = runtime.privacy_notice_path()
    typst_bin = runtime.typst_bin()

    runtime.validate_files(
        reference_path=reference_path,
        workdays_path=workdays_path,
        logo_path=logo_path,
        require_workdays=bool(plan["sync_compliance_history"])
        or "diff" in derive
        or "suspension_report" in derive,
        require_logo=bool({"overdue_report", "suspension_report"} & derive),
    )

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
    log_path = setup_logging(
        f"{run_date}_pipeline.log",
        log_dir=logs_root,
        level=level,
        fmt=str(runtime.logging_cfg.get("format", "text")),
        redact_long_numeric_ids=redact_long_numeric_ids,
        debug_http=debug_http,
        timezone_name=runtime.run_cfg.get("timezone"),
    )

    logging.info("Starting run_daily for %s", run_date)

    ensure_dir(input_root)
    ensure_dir(input_raw)
    ensure_dir(standardized_root)

    reference = load_school_reference(reference_path)
    adls_settings = load_adls_settings(runtime.config)
    sharepoint_settings = load_sharepoint_settings(runtime.config)

    options = RunDayOptions(
        derive_diff_enabled="diff" in derive,
        derive_overdue_report_enabled="overdue_report" in derive,
        derive_suspension_report_enabled="suspension_report" in derive,
        sharepoint_extract_inputs_enabled=bool(plan["extract_inputs"]),
        adls_download_inputs_enabled=bool(plan["download_inputs"]),
        adls_sync_compliance_history_enabled=bool(plan["sync_compliance_history"]),
        adls_upload_compliance_history_enabled=bool(plan["upload_compliance_history"]),
        adls_upload_combined_enabled=bool(plan["upload_combined"]),
        adls_upload_diff_enabled=bool(plan["upload_diff"]),
        sharepoint_publish_diff_enabled="diff" in publish,
        sharepoint_publish_overdue_pdf_enabled="overdue_pdf" in publish,
        sharepoint_publish_suspension_pdf_enabled="suspension_pdf" in publish,
        sharepoint_cleanup_pdfs_enabled=bool(plan["cleanup_sharepoint_pdfs"]),
        retain_local_inputs=args.retain_local_inputs,
        allow_compliance_history_additions=args.allow_compliance_history_additions,
        allow_compliance_history_bootstrap=args.allow_compliance_history_bootstrap,
        keep_typst_artifacts=args.keep_typst_artifacts,
        strict_headers=runtime.strict_headers,
        prune_history=args.prune_history,
        no_compile=args.no_compile,
        verbose=args.verbose,
        expected_input_count=args.expected_input_count,
        school_ids=args.school_id,
        levels=args.level,
        waves=args.wave,
        extract_upload_to_adls=bool(plan["upload_landing"]),
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


if __name__ == "__main__":
    raise SystemExit(main())
