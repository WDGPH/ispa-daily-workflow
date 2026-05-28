from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import polars as pl

from ispa_daily_workflow.domain.delivery.publish import publish_daily_outputs
from ispa_daily_workflow.io.adls import AdlsSettings, upload_paths
from ispa_daily_workflow.io.sharepoint_settings import SharePointSettings
from ispa_daily_workflow.models import ReportOutput
from ispa_daily_workflow.pipeline.run_artifacts import stage_summary, utc_now
from ispa_daily_workflow.reference import (
    SchoolReference,
    resolve_sharepoint_folder_for_school,
)
from ispa_daily_workflow.validation import project_delivery_contract


@dataclass(frozen=True)
class DailyPublishResult:
    stage_summaries: dict[str, dict[str, object]]
    adls_processed_uploads: list[str]
    adls_derived_uploads: list[str]
    sharepoint_uploaded_urls: list[str]
    sharepoint_deleted_overdue: list[str]


def _write_sharepoint_xlsx_exports(
    paths: list[Path],
    *,
    stream_label: str,
    schema_root: Path,
) -> list[Path]:
    parquet_paths = sorted(
        {path for path in paths if path.suffix.lower() == ".parquet"}
    )
    generated: list[Path] = []
    for parquet_path in parquet_paths:
        frame = pl.read_parquet(parquet_path)
        if stream_label == "diff":
            frame = project_delivery_contract(
                frame,
                output_id="sharepoint.panorama.diff.xlsx",
                schema_root=schema_root,
            )
        else:
            raise ValueError(
                f"Unsupported SharePoint XLSX export stream: {stream_label}"
            )
        xlsx_path = parquet_path.with_suffix(".xlsx")
        frame.write_excel(xlsx_path)
        generated.append(xlsx_path)
    if generated:
        logging.info(
            "Prepared %s %s XLSX file(s) for SharePoint upload",
            len(generated),
            stream_label,
        )
    return generated


def publish_stage(
    *,
    run_day: date,
    adls_settings: AdlsSettings,
    sharepoint_settings: SharePointSettings,
    reference: SchoolReference,
    schema_root: Path,
    combined_outputs: list[Path],
    compliance_history_outputs: list[Path],
    diff_outputs: list[Path],
    report_outputs: list[ReportOutput],
    adls_upload_combined_enabled: bool,
    adls_upload_compliance_history_enabled: bool,
    adls_upload_diff_enabled: bool,
    sharepoint_publish_diff_enabled: bool,
    sharepoint_publish_overdue_pdf_enabled: bool,
    sharepoint_publish_suspension_pdf_enabled: bool,
    sharepoint_cleanup_pdfs_enabled: bool,
    school_year_start_month: int,
) -> DailyPublishResult:
    combined_stage_outputs = sorted(set(combined_outputs))
    adls_processed_stage_outputs = (
        [path for path in combined_stage_outputs if path.suffix.lower() == ".parquet"]
        if adls_upload_combined_enabled
        else []
    )
    adls_derived_stage_outputs: list[Path] = []
    if adls_upload_compliance_history_enabled:
        adls_derived_stage_outputs.extend(
            path
            for path in compliance_history_outputs
            if path.suffix.lower() == ".parquet"
        )
    if adls_upload_diff_enabled:
        adls_derived_stage_outputs.extend(
            path for path in diff_outputs if path.suffix.lower() == ".parquet"
        )
    adls_derived_stage_outputs = sorted(set(adls_derived_stage_outputs))

    publish_adls_started = utc_now()
    adls_processed_uploads: list[str] = []
    adls_derived_uploads: list[str] = []
    publish_adls_status = "skipped"
    if adls_processed_stage_outputs or adls_derived_stage_outputs:
        publish_adls_status = "success"
        if adls_processed_stage_outputs:
            adls_processed_uploads = upload_paths(
                adls_settings,
                paths=adls_processed_stage_outputs,
                prefix=adls_settings.destinations.processed_prefix,
            )
        if adls_derived_stage_outputs:
            adls_derived_uploads = upload_paths(
                adls_settings,
                paths=adls_derived_stage_outputs,
                prefix=adls_settings.destinations.processed_prefix,
            )
    publish_adls_ended = utc_now()

    sharepoint_uploaded_urls: list[str] = []
    sharepoint_deleted_overdue: list[str] = []
    diff_publish_outputs = (
        _write_sharepoint_xlsx_exports(
            diff_outputs,
            stream_label="diff",
            schema_root=schema_root,
        )
        if sharepoint_publish_diff_enabled
        else []
    )
    report_publish_outputs = [
        report_output
        for report_output in report_outputs
        if (
            report_output.report_type == "overdue"
            and sharepoint_publish_overdue_pdf_enabled
        )
        or (
            report_output.report_type == "suspension"
            and sharepoint_publish_suspension_pdf_enabled
        )
    ]
    sharepoint_publish_requested = any(
        (
            diff_publish_outputs,
            report_publish_outputs,
        )
    )

    sharepoint_started = utc_now()
    sharepoint_status = "skipped"
    if sharepoint_publish_requested:
        summary = publish_daily_outputs(
            sharepoint_settings,
            diff_outputs=diff_publish_outputs,
            report_outputs=report_publish_outputs,
            secondary_labels=reference.secondary_labels,
            run_date=run_day,
            school_year_start_month=school_year_start_month,
            cleanup_report_pdfs=sharepoint_cleanup_pdfs_enabled,
            school_folder_resolver=lambda school_label: (
                resolve_sharepoint_folder_for_school(reference, school_label)
            ),
        )
        sharepoint_uploaded_urls.extend(summary.uploaded_urls)
        sharepoint_deleted_overdue.extend(summary.deleted_overdue)
        sharepoint_status = "success"
    sharepoint_ended = utc_now()

    return DailyPublishResult(
        stage_summaries={
            "publish_adls": stage_summary(
                status=publish_adls_status,
                started_at=publish_adls_started,
                ended_at=publish_adls_ended,
                processed_upload_count=len(adls_processed_uploads),
                derived_upload_count=len(adls_derived_uploads),
            ),
            "publish_sharepoint": stage_summary(
                status=sharepoint_status,
                started_at=sharepoint_started,
                ended_at=sharepoint_ended,
                uploaded_count=len(sharepoint_uploaded_urls),
                deleted_overdue_count=len(sharepoint_deleted_overdue),
            ),
        },
        adls_processed_uploads=adls_processed_uploads,
        adls_derived_uploads=adls_derived_uploads,
        sharepoint_uploaded_urls=sharepoint_uploaded_urls,
        sharepoint_deleted_overdue=sharepoint_deleted_overdue,
    )
