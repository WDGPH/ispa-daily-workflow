from __future__ import annotations

import logging
import re
from datetime import date
from typing import Callable

from panorama_compliance.io.sharepoint_graph import GraphRequestError
from panorama_compliance.io.sharepoint_paths import (
    _append_folder_url,
    _destination_url,
)
from panorama_compliance.io.sharepoint_session import SharePointSession
from panorama_compliance.io.sharepoint_settings import (
    SharePointPublishSummary,
    SharePointSettings,
)
from panorama_compliance.models import ReportOutput
from panorama_compliance.progress import tqdm


def publish_daily_outputs(
    settings: SharePointSettings,
    *,
    diff_outputs: list,
    report_outputs: list[ReportOutput],
    secondary_labels: set[str],
    run_date: date,
    school_year_start_month: int = 9,
    cleanup_report_pdfs: bool = False,
    school_folder_resolver: Callable[[str], str | None] | None = None,
) -> SharePointPublishSummary:
    uploaded_urls: list[str] = []
    deleted_overdue: list[str] = []
    resolver = school_folder_resolver or (lambda _label: None)

    with SharePointSession(settings) as session:
        if diff_outputs:
            uploaded_diff = session.upload_files_to_folder(
                folder_url=_destination_url(settings, "outputs.list_difference"),
                paths=diff_outputs,
                overwrite=True,
            )
            uploaded_urls.extend(
                item.remote_web_url for item in uploaded_diff if item.remote_web_url
            )
            logging.info(
                "Uploaded %s diff files to SharePoint list-difference folder",
                len(uploaded_diff),
            )

        cleaned_report_folders: set[str] = set()
        report_upload_count = 0
        cleanup_folder_count = 0
        cleanup_deleted_count = 0

        upload_candidates = [
            report_output
            for report_output in report_outputs
            if report_output.pdf_path.exists()
        ]
        upload_entries = [
            (
                report_output,
                _resolve_report_target_folder_url(
                    settings=settings,
                    report_output=report_output,
                    secondary_labels=secondary_labels,
                    resolver=resolver,
                ),
            )
            for report_output in upload_candidates
        ]
        if not cleanup_report_pdfs:
            _assert_no_final_summary_lock(
                session=session,
                upload_entries=upload_entries,
                run_date=run_date,
                school_year_start_month=school_year_start_month,
            )

        for report_output, target_folder_url in tqdm(
            upload_entries,
            desc="SharePoint PDF upload",
            unit="pdf",
        ):
            pdf_path = report_output.pdf_path

            cleanup_key = target_folder_url
            if cleanup_report_pdfs and cleanup_key not in cleaned_report_folders:
                cleanup_folder_count += 1
                try:
                    deleted = session.delete_folder_files(
                        folder_url=target_folder_url,
                        name_regex=_sharepoint_pdf_cleanup_regex(),
                        dry_run=False,
                    )
                except GraphRequestError as exc:
                    if exc.status_code != 404:
                        raise
                    deleted = []

                deleted_overdue.extend(
                    f"{target_folder_url}::{name}" for name in deleted
                )
                terminal_cleanup_regex = _terminal_cleanup_regex(
                    report_output=report_output,
                    run_date=run_date,
                    school_year_start_month=school_year_start_month,
                )
                if terminal_cleanup_regex is not None:
                    try:
                        terminal_deleted = session.delete_folder_files(
                            folder_url=target_folder_url,
                            name_regex=terminal_cleanup_regex,
                            dry_run=False,
                        )
                    except GraphRequestError as exc:
                        if exc.status_code != 404:
                            raise
                        terminal_deleted = []
                    deleted_overdue.extend(
                        f"{target_folder_url}::{name}" for name in terminal_deleted
                    )
                    deleted.extend(
                        name for name in terminal_deleted if name not in deleted
                    )
                cleaned_report_folders.add(cleanup_key)
                if deleted:
                    cleanup_deleted_count += len(deleted)
                    logging.debug(
                        "Deleted %s prior overdue/suspension PDFs from SharePoint folder %s",
                        len(deleted),
                        target_folder_url,
                    )
                else:
                    logging.debug(
                        "No prior overdue/suspension PDFs matched cleanup pattern in SharePoint folder %s",
                        target_folder_url,
                    )

            uploaded_pdf = session.upload_files_to_folder(
                folder_url=target_folder_url,
                paths=[pdf_path],
                overwrite=True,
            )
            uploaded_urls.extend(
                item.remote_web_url for item in uploaded_pdf if item.remote_web_url
            )
            report_upload_count += len(uploaded_pdf)

        if report_outputs:
            logging.info(
                "Uploaded %s PDF files to SharePoint school folders",
                report_upload_count,
            )
        if cleanup_report_pdfs:
            if cleanup_deleted_count:
                logging.info(
                    "Deleted %s prior overdue/suspension PDFs across %s SharePoint folder(s)",
                    cleanup_deleted_count,
                    cleanup_folder_count,
                )
            else:
                logging.info(
                    "No prior overdue/suspension PDFs matched cleanup pattern across %s SharePoint folder(s)",
                    cleanup_folder_count,
                )

    return SharePointPublishSummary(
        uploaded_urls=uploaded_urls,
        deleted_overdue=deleted_overdue,
    )


def preview_report_pdf_cleanup(
    settings: SharePointSettings,
    *,
    school_labels: list[str],
    secondary_labels: set[str],
    terminal_cleanup_school_labels: set[str] | None = None,
    run_date: date | None = None,
    school_year_start_month: int = 9,
    school_folder_resolver: Callable[[str], str | None] | None = None,
) -> list[str]:
    resolver = school_folder_resolver or (lambda _label: None)
    cleaned_report_folders: set[str] = set()
    candidates: list[str] = []

    with SharePointSession(settings) as session:
        ordered_labels = [
            label for label in sorted(set(school_labels), key=str.casefold) if label
        ]
        for school_label in tqdm(
            ordered_labels,
            desc="SharePoint PDF cleanup scan",
            unit="folder",
        ):
            dest_key = _sharepoint_pdf_destination_key(
                school_label,
                secondary_labels,
            )
            base_folder_url = _destination_url(settings, dest_key)
            folder_override = resolver(school_label)
            target_folder_url = _append_folder_url(
                base_folder_url,
                folder_override
                if folder_override
                else _safe_sharepoint_folder_name(school_label),
            )

            if target_folder_url in cleaned_report_folders:
                continue

            try:
                matches = session.delete_folder_files(
                    folder_url=target_folder_url,
                    name_regex=_sharepoint_pdf_cleanup_regex(),
                    dry_run=True,
                )
            except GraphRequestError as exc:
                if exc.status_code != 404:
                    raise
                matches = []

            candidates.extend(f"{target_folder_url}::{name}" for name in matches)
            if (
                terminal_cleanup_school_labels
                and school_label in terminal_cleanup_school_labels
                and run_date is not None
            ):
                terminal_regex = _terminal_cleanup_regex_for_school(
                    school_label=school_label,
                    terminal_status="suspension_period_complete",
                    run_date=run_date,
                    school_year_start_month=school_year_start_month,
                )
                if terminal_regex is not None:
                    try:
                        terminal_matches = session.delete_folder_files(
                            folder_url=target_folder_url,
                            name_regex=terminal_regex,
                            dry_run=True,
                        )
                    except GraphRequestError as exc:
                        if exc.status_code != 404:
                            raise
                        terminal_matches = []
                    candidates.extend(
                        f"{target_folder_url}::{name}" for name in terminal_matches
                    )
            cleaned_report_folders.add(target_folder_url)

    return list(dict.fromkeys(candidates))


def _resolve_report_target_folder_url(
    *,
    settings: SharePointSettings,
    report_output: ReportOutput,
    secondary_labels: set[str],
    resolver: Callable[[str], str | None],
) -> str:
    dest_key = _sharepoint_pdf_destination_key(
        report_output.school_label,
        secondary_labels,
    )
    base_folder_url = _destination_url(settings, dest_key)
    folder_override = resolver(report_output.school_label)
    return _append_folder_url(
        base_folder_url,
        folder_override
        if folder_override
        else _safe_sharepoint_folder_name(report_output.school_label),
    )


def _sanitize_report_token(value: str) -> str:
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


def _school_year_final_summary_filename(
    school_label: str,
    run_date: date,
    *,
    school_year_start_month: int = 9,
) -> str:
    start_year, end_year = _school_year_bounds(
        run_date,
        school_year_start_month=school_year_start_month,
    )
    school_token = _sanitize_report_token(school_label)
    return f"{start_year}_{end_year}_{school_token}_ISPA_FINAL_SUMMARY.pdf"


def _school_year_suspension_period_complete_filename(
    school_label: str,
    run_date: date,
    *,
    school_year_start_month: int = 9,
) -> str:
    start_year, end_year = _school_year_bounds(
        run_date,
        school_year_start_month=school_year_start_month,
    )
    school_token = _sanitize_report_token(school_label)
    return f"{start_year}_{end_year}_{school_token}_ISPA_SUSPENSION_PERIOD_COMPLETE.pdf"


def _final_summary_name_candidates(
    school_label: str,
    run_date: date,
    *,
    school_year_start_month: int = 9,
) -> set[str]:
    return {
        _school_year_final_summary_filename(
            school_label,
            run_date,
            school_year_start_month=school_year_start_month,
        ),
        _school_year_suspension_period_complete_filename(
            school_label,
            run_date,
            school_year_start_month=school_year_start_month,
        ),
    }


def _terminal_cleanup_regex(
    *,
    report_output: ReportOutput,
    run_date: date,
    school_year_start_month: int = 9,
) -> str | None:
    return _terminal_cleanup_regex_for_school(
        school_label=report_output.school_label,
        terminal_status=report_output.terminal_status,
        run_date=run_date,
        school_year_start_month=school_year_start_month,
    )


def _terminal_cleanup_regex_for_school(
    *,
    school_label: str,
    terminal_status: str | None,
    run_date: date,
    school_year_start_month: int = 9,
) -> str | None:
    if terminal_status != "suspension_period_complete":
        return None
    candidates = _final_summary_name_candidates(
        school_label,
        run_date,
        school_year_start_month=school_year_start_month,
    )
    escaped = "|".join(re.escape(name) for name in sorted(candidates))
    return rf"(?i)^(?:{escaped})$"


def _assert_no_final_summary_lock(
    *,
    session: SharePointSession,
    upload_entries: list[tuple[ReportOutput, str]],
    run_date: date,
    school_year_start_month: int = 9,
) -> None:
    seen_targets: set[tuple[str, str]] = set()
    existing_by_folder: dict[str, set[str]] = {}

    for report_output, target_folder_url in upload_entries:
        target_name = report_output.pdf_path.name
        target_key = (target_folder_url.casefold(), target_name.casefold())
        if target_key in seen_targets:
            raise RuntimeError(
                "SharePoint PDF upload plan contains duplicate target file "
                f"{target_name!r} in folder {target_folder_url!r}"
            )
        seen_targets.add(target_key)

        existing_names = existing_by_folder.get(target_folder_url)
        if existing_names is None:
            try:
                items = session.list_folder_items(folder_url=target_folder_url)
            except GraphRequestError as exc:
                if exc.status_code != 404:
                    raise
                existing_names = set()
            else:
                existing_names = {
                    item.name.casefold() for item in items if item.is_file and item.name
                }
            existing_by_folder[target_folder_url] = existing_names

        final_candidates = _final_summary_name_candidates(
            report_output.school_label,
            run_date,
            school_year_start_month=school_year_start_month,
        )
        matched = sorted(
            name for name in final_candidates if name.casefold() in existing_names
        )
        if not matched:
            continue

        raise RuntimeError(
            "Final summary lock exists for this school; refusing to upload a new PDF. "
            f"school={report_output.school_label!r} "
            f"run_date={run_date.strftime('%Y%m%d')} "
            f"existing_final={matched[0]!r} "
            f"attempted_file={target_name!r} "
            f"folder={target_folder_url!r}"
        )


def _safe_sharepoint_folder_name(value: str) -> str:
    text = value.strip().replace("\\", " ").replace("/", " ")
    text = " ".join(text.split())
    return text or "Unknown School"


def _sharepoint_pdf_destination_key(
    school_label: str,
    secondary_labels: set[str],
) -> str:
    if school_label in secondary_labels:
        return "outputs.pdf.secondary_root"
    return "outputs.pdf.elementary_root"


def _sharepoint_pdf_cleanup_regex() -> str:
    return r"(?i)_(OVERDUE|SUSPENSION|UPDATED[ _]SUSPENSION)[ _]LIST\.pdf$"
