from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import date
from pathlib import Path

import polars as pl

from ispa_daily_workflow.models import ReportOutput, ReportPaths
from ispa_daily_workflow.reference import SchoolReference
from ispa_daily_workflow.reports.report_writer import (
    build_report_paths,
    write_reports,
)


def render_report_outputs(
    report_type: str,
    df: pl.DataFrame,
    run_date: date,
    prev_business_day: date | None,
    output_root: Path,
    artifacts_root: Path,
    logo_path: Path,
    typst_bin: str,
    project_root: Path,
    no_compile: bool,
    prune_history: bool,
    keep_artifacts: bool,
    secondary_labels: set[str],
    target_school_labels: Sequence[str] | None = None,
    reference: SchoolReference | None = None,
    privacy_notice_path: Path | None = None,
    school_year_start_month: int = 9,
    verbose: bool = False,
) -> list[ReportOutput]:
    return write_reports(
        report_type,
        df,
        run_date,
        prev_business_day,
        output_root,
        artifacts_root,
        logo_path,
        typst_bin,
        project_root,
        no_compile,
        prune_history,
        keep_artifacts,
        secondary_labels,
        target_school_labels=target_school_labels,
        reference=reference,
        privacy_notice_path=privacy_notice_path,
        school_year_start_month=school_year_start_month,
        verbose=verbose,
    )


def cleanup_report_artifacts(
    artifacts_root: Path,
    report_types: Iterable[str],
) -> None:
    cleanup_typst_artifacts(artifacts_root, report_types)


def cleanup_typst_artifacts(artifacts_root: Path, report_types: Iterable[str]) -> None:
    for report_type in report_types:
        typst_dir = artifacts_root / "typst" / report_type
        if not typst_dir.exists():
            continue
        for path in typst_dir.glob("*.typ"):
            if path.is_file():
                path.unlink()


__all__ = [
    "ReportOutput",
    "ReportPaths",
    "build_report_paths",
    "cleanup_report_artifacts",
    "cleanup_typst_artifacts",
    "render_report_outputs",
]
