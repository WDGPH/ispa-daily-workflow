from __future__ import annotations

import traceback
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import polars as pl

from ispa_daily_workflow.io.adls import AdlsSettings
from ispa_daily_workflow.io.sharepoint_settings import SharePointSettings
from ispa_daily_workflow.io.workdays import load_workdays
from ispa_daily_workflow.models import AlertRecord, FileManifest, ReportOutput
from ispa_daily_workflow.pipeline.daily_extract import (
    DownloadInputsStageResult,
    ExtractStageResult,
    SyncComplianceHistoryStageResult,
    cleanup_local_scratch,
    clear_local_inputs,
    download_inputs_stage,
    extract_stage,
    sync_compliance_history_stage,
)
from ispa_daily_workflow.pipeline.daily_process import (
    ProcessStageResult,
    process_stage,
)
from ispa_daily_workflow.pipeline.run_artifacts import (
    daily_run_id,
    stage_summary,
    utc_now,
)
from ispa_daily_workflow.quality import build_alerts, write_run_artifact
from ispa_daily_workflow.reference import SchoolReference
from ispa_daily_workflow.validation import ensure_school_label_column

__all__ = [
    "DownloadInputsStageResult",
    "ExtractStageResult",
    "ProcessStageResult",
    "RunDayOptions",
    "RunDayResult",
    "SyncComplianceHistoryStageResult",
    "cleanup_local_scratch",
    "clear_local_inputs",
    "download_inputs_stage",
    "extract_stage",
    "process_stage",
    "run_day",
    "sync_compliance_history_stage",
]


@dataclass(frozen=True)
class RunDayOptions:
    derive_diff_enabled: bool
    derive_overdue_report_enabled: bool
    derive_suspension_report_enabled: bool
    sharepoint_extract_inputs_enabled: bool
    adls_download_inputs_enabled: bool
    adls_sync_compliance_history_enabled: bool
    adls_upload_compliance_history_enabled: bool
    adls_upload_combined_enabled: bool
    adls_upload_diff_enabled: bool
    sharepoint_publish_diff_enabled: bool
    sharepoint_publish_overdue_pdf_enabled: bool
    sharepoint_publish_suspension_pdf_enabled: bool
    sharepoint_cleanup_pdfs_enabled: bool
    retain_local_inputs: bool
    allow_compliance_history_additions: bool
    allow_compliance_history_bootstrap: bool
    keep_typst_artifacts: bool
    strict_headers: bool
    prune_history: bool
    no_compile: bool
    verbose: bool
    expected_input_count: int | None
    school_ids: list[str]
    levels: list[str]
    waves: list[str]
    extract_upload_to_adls: bool = True
    extract_landing_prefix: str | None = None
    download_landing_prefix: str | None = None


@dataclass(frozen=True)
class RunDayResult:
    run_id: str
    run_artifact_path: Path
    status: str
    warning_count: int
    error_count: int
    alerts: list[AlertRecord]
    stages: dict[str, dict[str, Any]]
    critical_messages: list[str]


def _describe_scope(options: RunDayOptions) -> str:
    if options.waves:
        values = [str(value).strip() for value in options.waves if str(value).strip()]
        return f"wave={','.join(values)}" if values else "wave=ALL"
    if options.levels:
        values = [str(value).strip() for value in options.levels if str(value).strip()]
        return f"level={','.join(values)}" if values else "level=ALL"
    if options.school_ids:
        values = [
            str(value).strip() for value in options.school_ids if str(value).strip()
        ]
        return f"school={','.join(values)}" if values else "school=ALL"
    return "wave=ALL"


def run_day(
    *,
    run_day: date,
    run_date: str,
    project_root: Path,
    input_raw: Path,
    standardized_dir: Path,
    combined_dir: Path,
    compliance_history_dir: Path,
    diff_dir: Path,
    reports_dir: Path,
    artifacts_root: Path,
    schema_root: Path,
    workdays_path: Path,
    reference: SchoolReference,
    adls_settings: AdlsSettings,
    sharepoint_settings: SharePointSettings,
    outputs_cfg: dict[str, Any],
    alerts_cfg: dict[str, Any],
    options: RunDayOptions,
    logo_path: Path,
    typst_bin: str,
    school_year_start_month: int = 9,
    privacy_notice_path: Path | None = None,
    log_path: Path | None = None,
) -> RunDayResult:
    run_id = daily_run_id(run_date)
    started_at = utc_now()

    stages: dict[str, dict[str, Any]] = {}
    alerts: list[AlertRecord] = []
    failure: dict[str, Any] | None = None

    manifests: list[FileManifest] = []
    datasets: dict[str, pl.DataFrame] = {}
    report_outputs: list[ReportOutput] = []
    file_outputs: list[Path] = []
    outputs_payload: dict[str, Any] = {}
    parse_failure_totals: dict[str, dict[str, int]] = {}

    current_stage = "initialize"
    status = "success"

    try:
        if (
            options.sharepoint_extract_inputs_enabled
            or options.adls_download_inputs_enabled
        ):
            clear_local_inputs(input_raw)

        current_stage = "extract"
        extract_started = utc_now()
        if options.sharepoint_extract_inputs_enabled:
            extract_result = extract_stage(
                run_day=run_day,
                run_date=run_date,
                input_raw=input_raw,
                schema_root=schema_root,
                reference=reference,
                sharepoint_settings=sharepoint_settings,
                adls_settings=adls_settings,
                upload_to_adls=options.extract_upload_to_adls,
                strict_headers=options.strict_headers,
                landing_prefix=options.extract_landing_prefix,
                overwrite_local=True,
            )
            stages["extract"] = stage_summary(
                status="success",
                started_at=extract_started,
                ended_at=utc_now(),
                enumerated_count=extract_result.enumerated_count,
                selected_count=extract_result.selected_count,
                downloaded_count=extract_result.selected_count,
                renamed_count=len(extract_result.renamed_outputs),
                uploaded_landing_count=len(extract_result.adls_uploaded_paths),
                created_window_start_utc=extract_result.created_window_start_utc,
                created_window_end_utc=extract_result.created_window_end_utc,
            )
        else:
            stages["extract"] = stage_summary(
                status="skipped",
                started_at=extract_started,
                ended_at=utc_now(),
            )

        current_stage = "download_inputs"
        download_started = utc_now()
        if options.adls_download_inputs_enabled:
            download_result = download_inputs_stage(
                run_date=run_date,
                input_raw=input_raw,
                adls_settings=adls_settings,
                landing_prefix=options.download_landing_prefix,
            )
            stages["download_inputs"] = stage_summary(
                status="success",
                started_at=download_started,
                ended_at=utc_now(),
                remote_prefix=download_result.remote_prefix,
                downloaded_count=len(download_result.downloaded_paths),
            )
        else:
            stages["download_inputs"] = stage_summary(
                status="skipped",
                started_at=download_started,
                ended_at=utc_now(),
            )

        current_stage = "sync_compliance_history"
        sync_started = utc_now()
        sync_result: SyncComplianceHistoryStageResult | None = None
        scope_description = _describe_scope(options)
        if options.adls_sync_compliance_history_enabled:
            sync_result = sync_compliance_history_stage(
                run_date=run_date,
                compliance_history_dir=compliance_history_dir,
                adls_settings=adls_settings,
                scope_description=scope_description,
            )
            if sync_result.warning_alert is not None:
                alerts.append(sync_result.warning_alert)
            stages["sync_compliance_history"] = stage_summary(
                status="success",
                started_at=sync_started,
                ended_at=utc_now(),
                synced_count=len(sync_result.synced_paths),
            )
        else:
            stages["sync_compliance_history"] = stage_summary(
                status="skipped",
                started_at=sync_started,
                ended_at=utc_now(),
            )

        workdays = load_workdays(workdays_path) if workdays_path.exists() else {}
        workday_info = workdays.get(run_day)
        previous_day = workday_info.previous_business_day if workday_info else None
        previous_date = previous_day.strftime("%Y%m%d") if previous_day else None

        if (
            sync_result is not None
            and sync_result.warning_alert is not None
            and previous_day is not None
            and not options.allow_compliance_history_bootstrap
        ):
            raise RuntimeError(
                "No prior compliance_history snapshots were found in ADLS processed storage "
                f"before run_date={run_date} (scope: {scope_description}). "
                "Refusing to bootstrap compliance_history on a non-initial business day; "
                "rerun with explicit bootstrap override "
                "(update_state: --init-compliance-history; run_daily: --allow-compliance-history-bootstrap) "
                "only when intentional."
            )

        current_stage = "process"
        process_result = process_stage(
            run_day=run_day,
            run_date=run_date,
            previous_day=previous_day,
            previous_date=previous_date,
            project_root=project_root,
            input_raw=input_raw,
            standardized_dir=standardized_dir,
            combined_dir=combined_dir,
            compliance_history_dir=compliance_history_dir,
            diff_dir=diff_dir,
            reports_dir=reports_dir,
            artifacts_root=artifacts_root,
            schema_root=schema_root,
            reference=reference,
            outputs_cfg=outputs_cfg,
            options=options,
            adls_settings=adls_settings,
            sharepoint_settings=sharepoint_settings,
            logo_path=logo_path,
            typst_bin=typst_bin,
            privacy_notice_path=privacy_notice_path,
            school_year_start_month=school_year_start_month,
        )
        stages.update(process_result.stage_summaries)

        alerts.extend(process_result.runtime_alerts)
        quality_alerts = build_alerts(
            current_df=ensure_school_label_column(process_result.current_df),
            previous_df=ensure_school_label_column(process_result.previous_df)
            if process_result.previous_df is not None
            else None,
            expected_input_count=options.expected_input_count,
            observed_input_count=stages["process"].get("observed_input_count", 0),
            missing_input_threshold=int(alerts_cfg.get("missing_input_threshold", 0)),
            percent_change_threshold=float(
                alerts_cfg.get("percent_change_threshold", 0.25)
            ),
        )
        alerts.extend(quality_alerts)

        manifests = process_result.manifests
        datasets = process_result.datasets
        report_outputs = process_result.report_outputs
        file_outputs = process_result.file_outputs
        parse_failure_totals = process_result.parse_counter_totals
        outputs_payload = {
            "adls_processed_uploads": process_result.adls_processed_uploads,
            "adls_derived_uploads": process_result.adls_derived_uploads,
            "sharepoint_uploaded_urls": process_result.sharepoint_uploaded_urls,
            "sharepoint_deleted_overdue": process_result.sharepoint_deleted_overdue,
        }

    except Exception as exc:  # noqa: BLE001 - pipeline boundary records failure evidence
        status = "failed"
        trace = traceback.format_exc()
        failure = {
            "stage": current_stage,
            "error_type": type(exc).__name__,
            "error_message": str(exc),
            "traceback": trace,
        }
        alerts.append(
            AlertRecord(
                code="pipeline_failure",
                level="error",
                message=f"Daily pipeline failed during stage {current_stage}: {exc}",
                context={"run_date": run_date, "stage": current_stage},
            )
        )
        now = utc_now()
        existing = stages.get(current_stage)
        if existing is None:
            stages[current_stage] = stage_summary(
                status="failed",
                started_at=now,
                ended_at=now,
                message=str(exc),
            )
        else:
            existing["status"] = "failed"
            existing["message"] = str(exc)

    finally:
        cleanup_started = utc_now()
        if options.retain_local_inputs:
            stages["cleanup"] = stage_summary(
                status="skipped",
                started_at=cleanup_started,
                ended_at=utc_now(),
            )
        else:
            try:
                cleanup_local_scratch(
                    input_raw=input_raw,
                    standardized_dir=standardized_dir,
                )
                stages["cleanup"] = stage_summary(
                    status="success",
                    started_at=cleanup_started,
                    ended_at=utc_now(),
                )
            except Exception as cleanup_exc:  # noqa: BLE001 - cleanup must not mask run evidence
                alerts.append(
                    AlertRecord(
                        code="cleanup_failed",
                        level="warning",
                        message=f"Local scratch cleanup failed: {cleanup_exc}",
                        context={"run_date": run_date},
                    )
                )
                stages["cleanup"] = stage_summary(
                    status="failed",
                    started_at=cleanup_started,
                    ended_at=utc_now(),
                    message=str(cleanup_exc),
                )

    if log_path is not None:
        outputs_payload["log_path"] = str(log_path)

    ended_at = utc_now()
    run_artifact_path = write_run_artifact(
        runs_dir=artifacts_root / "runs",
        run_id=run_id,
        run_date=run_day,
        mode="run_daily",
        status=status,
        started_at=started_at,
        ended_at=ended_at,
        stages=stages,
        alerts=alerts,
        manifests=manifests,
        datasets=datasets,
        report_outputs=report_outputs,
        file_outputs=file_outputs,
        outputs=outputs_payload,
        failure=failure,
        extra={
            "derive_diff_enabled": options.derive_diff_enabled,
            "derive_overdue_report_enabled": options.derive_overdue_report_enabled,
            "derive_suspension_report_enabled": options.derive_suspension_report_enabled,
            "sharepoint_extract_inputs_enabled": options.sharepoint_extract_inputs_enabled,
            "adls_download_inputs_enabled": options.adls_download_inputs_enabled,
            "adls_sync_compliance_history_enabled": options.adls_sync_compliance_history_enabled,
            "adls_upload_compliance_history_enabled": options.adls_upload_compliance_history_enabled,
            "adls_upload_combined_enabled": options.adls_upload_combined_enabled,
            "adls_upload_diff_enabled": options.adls_upload_diff_enabled,
            "sharepoint_publish_diff_enabled": options.sharepoint_publish_diff_enabled,
            "sharepoint_publish_overdue_pdf_enabled": (
                options.sharepoint_publish_overdue_pdf_enabled
            ),
            "sharepoint_publish_suspension_pdf_enabled": (
                options.sharepoint_publish_suspension_pdf_enabled
            ),
            "sharepoint_cleanup_pdfs_enabled": options.sharepoint_cleanup_pdfs_enabled,
            "allow_compliance_history_additions": options.allow_compliance_history_additions,
            "allow_compliance_history_bootstrap": options.allow_compliance_history_bootstrap,
            "retain_local_inputs": options.retain_local_inputs,
            "parse_failure_counters": parse_failure_totals,
        },
    )

    warning_count = sum(1 for alert in alerts if alert.level.lower() == "warning")
    error_count = sum(1 for alert in alerts if alert.level.lower() == "error")
    critical_messages = [
        alert.message for alert in alerts if alert.level.lower() in {"warning", "error"}
    ]

    return RunDayResult(
        run_id=run_id,
        run_artifact_path=run_artifact_path,
        status=status,
        warning_count=warning_count,
        error_count=error_count,
        alerts=alerts,
        stages=stages,
        critical_messages=critical_messages[:10],
    )
