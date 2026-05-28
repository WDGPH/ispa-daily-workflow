#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

import polars as pl

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_ROOT))

from panorama_compliance.compliance_history import (
    discover_latest_compliance_history_by_slice,
)
from panorama_compliance.io.readers import read_dataframe_with_schema
from panorama_compliance.io.workdays import load_workdays, parse_run_date
from panorama_compliance.normalize import normalize_compliance_dataframe
from panorama_compliance.pipeline.workflow_config import load_workflow_config
from panorama_compliance.quality import write_manifest
from panorama_compliance.reference import load_school_reference
from panorama_compliance.reports.service import (
    cleanup_report_artifacts,
    render_report_outputs,
)
from panorama_compliance.validation import (
    ensure_school_label_column,
    require_previous_business_day,
)
from panorama_compliance.schema import resolve_dataset_schema

DEFAULT_LOGO_PATH = Path("assets/logo.pdf")
DEFAULT_REFERENCE_PATH = Path("school_reference.json")
DEFAULT_COMBINED_DIR = Path("output/combined")
DEFAULT_COMPLIANCE_HISTORY_DIR = Path("output/compliance_history")
DEFAULT_OUTPUT_ROOT = Path("output/reports")
DEFAULT_ARTIFACTS_ROOT = Path("artifacts")
DEFAULT_QUALITY_DIR = Path("artifacts/data_quality")


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Render overdue and suspension reports from combined/compliance_history datasets."
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
        "--input", type=Path, nargs="*", help="Input file(s) to render."
    )
    parser.add_argument(
        "--report", choices=("auto", "overdue", "suspension", "both"), default="auto"
    )
    parser.add_argument(
        "--overdue-source",
        choices=("compliance_history", "combined"),
        default="compliance_history",
        help=(
            "Input source for overdue reports: compliance_history (active rows only) "
            "or combined noncompliant files."
        ),
    )
    parser.add_argument("--workdays", type=Path, default=None)
    parser.add_argument("--combined-dir", type=Path, default=DEFAULT_COMBINED_DIR)
    parser.add_argument(
        "--compliance_history-dir",
        type=Path,
        default=DEFAULT_COMPLIANCE_HISTORY_DIR,
    )
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--artifacts-root", type=Path, default=DEFAULT_ARTIFACTS_ROOT)
    parser.add_argument("--quality-dir", type=Path, default=DEFAULT_QUALITY_DIR)
    parser.add_argument("--logo", type=Path, default=DEFAULT_LOGO_PATH)
    parser.add_argument("--typst-bin", type=str, default="typst")
    parser.add_argument("--reference", type=Path, default=DEFAULT_REFERENCE_PATH)
    parser.add_argument("--no-compile", action="store_true")
    parser.add_argument("--prune-history", action="store_true")
    parser.add_argument("--keep-artifacts", action="store_true")
    parser.add_argument("--verbose", action="store_true")
    return parser.parse_args(argv)


def _read_frame(path: Path) -> pl.DataFrame:
    if path.suffix.lower() == ".parquet":
        return pl.read_parquet(path)
    if path.suffix.lower() in {".xlsx", ".xls"}:
        dataset_id = (
            "processed.panorama.suspension_compliance_history"
            if "_compliance_history" in path.name
            else "processed.panorama.noncompliant"
        )
        schema = resolve_dataset_schema(dataset_id, schema_root=PROJECT_ROOT / "schema")
        return read_dataframe_with_schema(
            path,
            schema,
            file_format=path.suffix.lstrip("."),
            as_string=True,
        )
    raise ValueError(f"Unsupported report input: {path}")


def _infer_report_type(path: Path) -> str:
    if "_compliance_history" in path.name:
        return "suspension"
    return "overdue"


def _discover_overdue_inputs(
    run_date: str,
    *,
    source: str,
    combined_dir: Path,
    compliance_history_dir: Path,
) -> list[Path]:
    if source == "compliance_history":
        latest = discover_latest_compliance_history_by_slice(
            compliance_history_dir, run_date=run_date
        )
        return sorted(latest.values())
    files = sorted(combined_dir.glob(f"{run_date}_panorama_*_noncompliant.parquet"))
    if files:
        return files
    return sorted(combined_dir.glob(f"{run_date}_panorama_*_noncompliant.xlsx"))


def _discover_suspension_inputs(
    run_date: str, *, compliance_history_dir: Path
) -> list[Path]:
    latest = discover_latest_compliance_history_by_slice(
        compliance_history_dir, run_date=run_date
    )
    return sorted(latest.values())


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    run_day = parse_run_date(args.run_date)
    run_date = run_day.strftime("%Y%m%d")

    runtime = load_workflow_config(args, project_root=PROJECT_ROOT)

    if args.reference == DEFAULT_REFERENCE_PATH:
        reference_path = runtime.required_path("reference")
    else:
        reference_path = runtime.resolve_path(args.reference, "--reference")

    if args.workdays is not None:
        workdays_path = runtime.resolve_path(args.workdays, "--workdays")
    else:
        workdays_path = runtime.run_path("workdays_csv")

    configured_output_root = runtime.required_path("output_root")
    configured_artifacts_root = runtime.required_path("artifacts_root")

    if args.logo == DEFAULT_LOGO_PATH:
        logo_path = runtime.logo_path()
    else:
        logo_path = runtime.optional_path(args.logo) or args.logo
    privacy_notice_path = runtime.privacy_notice_path()
    typst_bin = runtime.typst_bin(args.typst_bin)

    if args.combined_dir == DEFAULT_COMBINED_DIR:
        combined_dir = configured_output_root / "combined"
    else:
        combined_dir = runtime.resolve_path(args.combined_dir, "--combined-dir")
    if args.compliance_history_dir == DEFAULT_COMPLIANCE_HISTORY_DIR:
        compliance_history_dir = configured_output_root / "compliance_history"
    else:
        compliance_history_dir = runtime.resolve_path(
            args.compliance_history_dir,
            "--compliance_history-dir",
        )
    if args.output_root == DEFAULT_OUTPUT_ROOT:
        output_root = configured_output_root / "reports"
    else:
        output_root = runtime.resolve_path(args.output_root, "--output-root")
    if args.artifacts_root == DEFAULT_ARTIFACTS_ROOT:
        artifacts_root = configured_artifacts_root
    else:
        artifacts_root = runtime.resolve_path(
            args.artifacts_root,
            "--artifacts-root",
        )
    if args.quality_dir == DEFAULT_QUALITY_DIR:
        quality_dir = artifacts_root / "data_quality"
    else:
        quality_dir = runtime.resolve_path(args.quality_dir, "--quality-dir")

    runtime.validate_files(
        reference_path=reference_path,
    )

    reference = load_school_reference(reference_path)

    jobs: list[tuple[Path, str]] = []
    if args.input:
        for path in sorted(args.input):
            report_type = (
                _infer_report_type(path)
                if args.report == "auto"
                else ("suspension" if args.report == "suspension" else "overdue")
            )
            if args.report == "both":
                report_type = _infer_report_type(path)
            jobs.append((path, report_type))
    else:
        if args.report in {"auto", "overdue", "both"}:
            for path in _discover_overdue_inputs(
                run_date,
                source=args.overdue_source,
                combined_dir=combined_dir,
                compliance_history_dir=compliance_history_dir,
            ):
                jobs.append((path, "overdue"))
        if args.report in {"auto", "suspension", "both"}:
            for path in _discover_suspension_inputs(
                run_date, compliance_history_dir=compliance_history_dir
            ):
                jobs.append((path, "suspension"))

    if not jobs:
        print("No report inputs found.")
        return 1

    needs_workdays = any(report_type == "suspension" for _, report_type in jobs)
    runtime.validate_files(
        reference_path=reference_path,
        workdays_path=workdays_path,
        logo_path=logo_path,
        require_workdays=needs_workdays,
        require_logo=True,
    )

    prev_business_day = None
    if needs_workdays:
        workdays = load_workdays(workdays_path)
        workday_info = workdays.get(run_day)
        prev_business_day = workday_info.previous_business_day if workday_info else None
        require_previous_business_day(
            previous_business_day=prev_business_day,
            run_date=run_date,
            label="suspension report generation",
        )

    report_outputs = []
    attempted_report_types = {report_type for _, report_type in jobs}
    try:
        for path, report_type in jobs:
            frame = normalize_compliance_dataframe(
                _read_frame(path), reference=reference
            )
            frame = ensure_school_label_column(frame)
            outputs = render_report_outputs(
                report_type,
                frame,
                run_day,
                prev_business_day,
                output_root,
                artifacts_root,
                logo_path,
                typst_bin,
                PROJECT_ROOT,
                args.no_compile,
                args.prune_history,
                args.keep_artifacts,
                reference.secondary_labels,
                reference=reference,
                privacy_notice_path=privacy_notice_path,
                school_year_start_month=runtime.school_year_start_month,
                verbose=args.verbose,
            )
            report_outputs.extend(outputs)
    finally:
        if not args.no_compile and not args.keep_artifacts and attempted_report_types:
            cleanup_report_artifacts(artifacts_root, attempted_report_types)

    timestamp = datetime.now().strftime("%Y%m%dT%H%M%S")
    manifest_path = write_manifest(
        quality_dir=quality_dir,
        timestamp=timestamp,
        run_date=run_day,
        mode="build_reports",
        report_outputs=report_outputs,
        file_outputs=[output.pdf_path for output in report_outputs],
        extra={
            "input_count": len(jobs),
            "report_mode": args.report,
            "overdue_source": args.overdue_source,
        },
    )

    print(f"Generated {len(report_outputs)} reports")
    print(f"Manifest: {manifest_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
