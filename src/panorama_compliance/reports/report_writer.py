from __future__ import annotations

import re
import subprocess
from datetime import date
from pathlib import Path
from typing import Sequence

import polars as pl

from panorama_compliance.constants import OUTDATED_PDF_PATTERN
from panorama_compliance.models import ReportOutput, ReportPaths
from panorama_compliance.normalize import sort_students
from panorama_compliance.progress import tqdm
from panorama_compliance.reference import SchoolReference, resolve_school_record
from panorama_compliance.templates import (
    build_overdue_typst,
    build_suspension_period_complete_typst,
    build_suspension_typst,
)
from panorama_compliance.validation.catalog import RULE_PREVIOUS_BUSINESS_DAY_ID
from panorama_compliance.validation.frames import collect_school_labels


def remove_outdated_files(folder: Path) -> None:
    for path in folder.iterdir():
        if path.is_file() and OUTDATED_PDF_PATTERN.match(path.name):
            path.unlink()


def compile_typst(
    typst_bin: str, typst_path: Path, pdf_path: Path, project_root: Path
) -> None:
    subprocess.run(
        [
            typst_bin,
            "compile",
            "--root",
            str(project_root),
            str(typst_path),
            str(pdf_path),
        ],
        check=True,
    )


def _extract_school_id(school_label: str) -> str:
    if " - " in school_label:
        candidate = school_label.rsplit(" - ", maxsplit=1)[-1].strip()
        if candidate:
            return candidate
    return ""


def _sanitize_identifier(value: str) -> str:
    return re.sub(r"[^\w]+", "_", value).strip("_")


def _school_year_bounds(
    run_date: date,
    *,
    school_year_start_month: int,
) -> tuple[int, int]:
    start_year = (
        run_date.year
        if run_date.month >= school_year_start_month
        else run_date.year - 1
    )
    return start_year, start_year + 1


def _normalize_typst_asset_path(asset_path: Path, project_root: Path) -> Path:
    """Return a Typst-friendly project-relative path for --root compilation."""
    root = project_root.expanduser().resolve()
    candidate = asset_path.expanduser()

    if candidate.is_absolute():
        resolved = candidate.resolve()
        try:
            return resolved.relative_to(root)
        except ValueError as exc:
            raise ValueError(
                "Typst asset path must be inside project root when compiling "
                f"with --root. asset={candidate} root={root}"
            ) from exc

    return candidate


def _load_privacy_notice_typst(
    *,
    privacy_notice_path: Path | None,
    project_root: Path,
) -> str | None:
    candidate = privacy_notice_path or (project_root / "profile" / "privacy_notice.typ")
    resolved = candidate.expanduser()
    if not resolved.is_absolute():
        resolved = (project_root / resolved).resolve()
    if not resolved.exists() or not resolved.is_file():
        return None
    content = resolved.read_text(encoding="utf-8").strip()
    return content or None


def build_report_paths(
    output_root: Path,
    artifacts_root: Path,
    report_type: str,
    school: str,
    run_date: date,
    secondary_labels: set[str],
    final_report: bool = False,
    suspension_period_complete: bool = False,
    school_year_start_month: int = 9,
) -> ReportPaths:
    category = (
        "Secondary_Schools" if school in secondary_labels else "Elementary_Schools"
    )
    school_label = school.strip()
    output_dir = output_root / category / school_label
    typst_dir = artifacts_root / "typst" / report_type
    school_id = _extract_school_id(school_label)
    identifier = _sanitize_identifier((school_id or school_label).strip())
    date_prefix = run_date.strftime("%Y%m%d")
    typst_path = typst_dir / f"{date_prefix}_{identifier}_{report_type}.typ"
    school_token = _sanitize_identifier(school_label)
    if final_report and suspension_period_complete:
        raise ValueError(
            "build_report_paths received conflicting terminal flags: "
            "final_report and suspension_period_complete"
        )
    if final_report:
        start_year, end_year = _school_year_bounds(
            run_date,
            school_year_start_month=school_year_start_month,
        )
        pdf_path = (
            output_dir
            / f"{start_year}_{end_year}_{school_token}_ISPA_FINAL_SUMMARY.pdf"
        )
    elif suspension_period_complete:
        start_year, end_year = _school_year_bounds(
            run_date,
            school_year_start_month=school_year_start_month,
        )
        pdf_path = (
            output_dir
            / f"{start_year}_{end_year}_{school_token}_ISPA_SUSPENSION_PERIOD_COMPLETE.pdf"
        )
    else:
        suffix = "SUSPENSION_LIST" if report_type == "suspension" else "OVERDUE_LIST"
        pdf_path = output_dir / f"{date_prefix}_{school_token}_{suffix}.pdf"
    return ReportPaths(output_dir=output_dir, typst_path=typst_path, pdf_path=pdf_path)


def _format_date(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, date):
        return value.strftime("%Y-%m-%d")
    text = str(value).strip()
    return text


def _id_stats(df: pl.DataFrame, id_column: str = "client_id") -> dict[str, int]:
    if id_column not in df.columns:
        return {
            "total_rows": df.height,
            "missing_id_count": df.height,
            "duplicate_id_count": 0,
        }
    ids = df.select(
        pl.col(id_column).cast(pl.Utf8, strict=False).str.strip_chars().alias(id_column)
    )
    missing = ids.filter(pl.col(id_column).is_null() | (pl.col(id_column) == "")).height
    duplicates = (
        ids.filter(pl.col(id_column).is_not_null() & (pl.col(id_column) != ""))
        .group_by(id_column)
        .len()
        .filter(pl.col("len") > 1)
        .height
    )
    return {
        "total_rows": df.height,
        "missing_id_count": missing,
        "duplicate_id_count": duplicates,
    }


def _resolve_report_labels(
    df: pl.DataFrame,
    *,
    target_school_labels: Sequence[str] | None,
) -> list[str]:
    labels = set(collect_school_labels(df))
    if target_school_labels:
        for label in target_school_labels:
            text = str(label).strip()
            if text:
                labels.add(text)
    return sorted(labels, key=str.casefold)


def _latest_rescinded_date(
    df: pl.DataFrame,
    *,
    run_date: date,
) -> str | None:
    if "compliant" not in df.columns or df.is_empty():
        return None
    latest = (
        df.filter(pl.col("compliant").is_not_null() & (pl.col("compliant") <= run_date))
        .select(pl.col("compliant").max().alias("compliant"))
        .item()
    )
    if latest is None:
        return None
    return _format_date(latest)


def _suspension_period_complete_date(
    *,
    school_label: str,
    run_date: date,
    reference: SchoolReference | None,
) -> date | None:
    if reference is None:
        return None
    record = resolve_school_record(reference, school_label)
    if (
        record is None
        or record.suspension_window_end is None
        or run_date <= record.suspension_window_end
    ):
        return None
    return record.suspension_window_end


def write_reports(
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
    def _log(message: str, detail: bool = False) -> None:
        if detail and not verbose:
            return
        print(message)

    if report_type == "suspension" and prev_business_day is None:
        raise ValueError(
            "VALIDATION FAIL "
            f"[{RULE_PREVIOUS_BUSINESS_DAY_ID}] "
            f"previous business day is required for suspension reports on {run_date}"
        )

    if "school_label" not in df.columns:
        raise ValueError("Report dataframe is missing school_label")

    # Overdue reports sourced from compliance_history must only include active rows.
    if report_type == "overdue" and "compliant" in df.columns:
        df = df.filter(pl.col("compliant").is_null() | (pl.col("compliant") > run_date))

    labels = _resolve_report_labels(df, target_school_labels=target_school_labels)
    if not labels:
        _log(f"No {report_type} rows found.")
        return []
    if df.is_empty():
        _log(
            f"No {report_type} rows found in source data; generating "
            f"{len(labels)} all-up-to-date report(s).",
            detail=True,
        )

    outputs: list[ReportOutput] = []
    typst_logo_path = _normalize_typst_asset_path(logo_path, project_root)
    privacy_notice_typst = _load_privacy_notice_typst(
        privacy_notice_path=privacy_notice_path,
        project_root=project_root,
    )
    if not (project_root / typst_logo_path).exists():
        raise FileNotFoundError(
            f"Logo asset not found under project root: {project_root / typst_logo_path}"
        )

    for school in tqdm(labels, desc=f"Rendering {report_type} PDFs", unit="school"):
        school_df = sort_students(df.filter(pl.col("school_label") == school))
        suspension_period_complete_date = _suspension_period_complete_date(
            school_label=str(school),
            run_date=run_date,
            reference=reference,
        )
        if suspension_period_complete_date is not None:
            paths = build_report_paths(
                output_root,
                artifacts_root,
                report_type,
                str(school),
                run_date,
                secondary_labels,
                suspension_period_complete=True,
                school_year_start_month=school_year_start_month,
            )
            typst_content = build_suspension_period_complete_typst(
                str(school),
                run_date,
                suspension_period_complete_date,
                typst_logo_path,
                privacy_notice_typst,
            )
            output = ReportOutput(
                report_type=report_type,
                school_label=str(school),
                pdf_path=paths.pdf_path,
                counts={},
                id_stats={},
                terminal_status="suspension_period_complete",
            )
        elif report_type == "suspension":
            assert prev_business_day is not None
            active = school_df.filter(
                pl.col("compliant").is_null() | (pl.col("compliant") > run_date)
            )
            if "report_rescinded" in school_df.columns:
                rescinded = school_df.filter(
                    pl.col("compliant").is_not_null()
                    & (pl.col("compliant") <= run_date)
                    & (pl.col("compliant") >= prev_business_day)
                    & pl.col("report_rescinded").fill_null(False)
                ).sort(["compliant", "last_name"], descending=[True, False])
            else:
                rescinded = school_df.filter(
                    pl.col("compliant").is_not_null()
                    & (pl.col("compliant") <= run_date)
                    & (pl.col("compliant") > prev_business_day)
                ).sort(["compliant", "last_name"], descending=[True, False])

            active_rows = [
                (
                    row[0],
                    row[1],
                    _format_date(row[2]),
                )
                for row in active.select(
                    ["last_name", "first_name", "date_of_birth"]
                ).iter_rows()
            ]
            rescinded_rows = [
                (
                    row[0],
                    row[1],
                    _format_date(row[2]),
                )
                for row in rescinded.select(
                    ["last_name", "first_name", "date_of_birth"]
                ).iter_rows()
            ]

            if not active_rows and not rescinded_rows and target_school_labels is None:
                _log(
                    f"{school}: no active suspensions or rescinds; skipping",
                    detail=True,
                )
                continue

            final_report = not active_rows and not rescinded_rows
            summary_label = "Final Summary" if final_report else None
            final_rescinded_date = (
                _latest_rescinded_date(school_df, run_date=run_date)
                if final_report
                else None
            )
            paths = build_report_paths(
                output_root,
                artifacts_root,
                report_type,
                str(school),
                run_date,
                secondary_labels,
                final_report=final_report,
                school_year_start_month=school_year_start_month,
            )
            typst_content = build_suspension_typst(
                str(school),
                run_date,
                prev_business_day,
                active_rows,
                rescinded_rows,
                typst_logo_path,
                privacy_notice_typst,
                summary_label=summary_label,
                final_rescinded_date=final_rescinded_date,
            )
            output = ReportOutput(
                report_type=report_type,
                school_label=str(school),
                pdf_path=paths.pdf_path,
                counts={"active": len(active_rows), "rescinded": len(rescinded_rows)},
                id_stats={
                    "active_missing_client_id_count": _id_stats(active)[
                        "missing_id_count"
                    ],
                    "rescinded_missing_client_id_count": _id_stats(rescinded)[
                        "missing_id_count"
                    ],
                },
                terminal_status="final_summary" if final_report else None,
            )
        else:
            overdue_rows = [
                (
                    row[0],
                    row[1],
                    _format_date(row[2]),
                )
                for row in school_df.select(
                    ["last_name", "first_name", "date_of_birth"]
                ).iter_rows()
            ]
            final_report = not overdue_rows
            summary_label = "Final Summary" if final_report else None
            paths = build_report_paths(
                output_root,
                artifacts_root,
                report_type,
                str(school),
                run_date,
                secondary_labels,
                final_report=final_report,
                school_year_start_month=school_year_start_month,
            )
            typst_content = build_overdue_typst(
                str(school),
                run_date,
                overdue_rows,
                typst_logo_path,
                privacy_notice_typst,
                summary_label=summary_label,
            )
            stats = _id_stats(school_df)
            output = ReportOutput(
                report_type=report_type,
                school_label=str(school),
                pdf_path=paths.pdf_path,
                counts={"overdue": len(overdue_rows)},
                id_stats={"missing_client_id_count": stats["missing_id_count"]},
                terminal_status="final_summary" if final_report else None,
            )

        paths.output_dir.mkdir(parents=True, exist_ok=True)
        paths.typst_path.parent.mkdir(parents=True, exist_ok=True)

        if prune_history:
            remove_outdated_files(paths.output_dir)

        paths.typst_path.write_text(typst_content, encoding="utf-8")
        if no_compile:
            _log(f"Wrote Typst template: {paths.typst_path}", detail=True)
            continue

        compile_typst(typst_bin, paths.typst_path, paths.pdf_path, project_root)
        _log(f"Wrote PDF: {paths.pdf_path}", detail=True)
        if not keep_artifacts:
            paths.typst_path.unlink(missing_ok=True)
        outputs.append(output)

    return outputs
