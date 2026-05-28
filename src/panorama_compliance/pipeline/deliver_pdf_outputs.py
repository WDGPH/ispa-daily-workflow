from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import logging
from pathlib import Path
from typing import Callable

import polars as pl

from panorama_compliance.domain.pear.state import (
    write_pear_authoritative_suspension_outputs,
)
from panorama_compliance.domain.delivery.pear_state import (
    apply_wave_scope_filter as _apply_wave_scope_filter,
    empty_pear_report_frames_for_scope as _empty_pear_report_frames_for_scope,
    load_scoped_pear_authoritative_baseline_frames as _load_scoped_pear_authoritative_baseline_frames,
    load_scoped_pear_state_frames as _load_scoped_pear_state_frames,
    post_window_school_labels as _post_window_school_labels,
    scope_is_after_suspension_window as _scope_is_after_suspension_window,
)
from panorama_compliance.domain.delivery.publish import (
    preview_report_pdf_cleanup,
    publish_daily_outputs,
)
from panorama_compliance.domain.delivery.routing import (
    DeliveryScope,
    collect_scope_school_labels,
    apply_scope_filter,
)
from panorama_compliance.io.adapters import StateStore
from panorama_compliance.pipeline.delivery_runtime import IOMode
from panorama_compliance.reference import (
    SchoolReference,
    resolve_sharepoint_folder_for_school,
)
from panorama_compliance.reports.service import (
    build_report_paths,
    cleanup_report_artifacts,
    render_report_outputs,
)
from panorama_compliance.schema import ValidationError
from panorama_compliance.validation import (
    RULE_DELIVERY_CONTRACT_ID,
    RULE_PREVIOUS_BUSINESS_DAY_ID,
    RULE_PREVIOUS_SCOPE_DATA_ID,
    RuleResult,
    ValidationSummary,
    ensure_school_label_column,
    previous_scope_data_file_warning,
    require_previous_business_day,
    validate_report_delivery_contract,
)
from panorama_compliance.pipeline.deliver_tabular_outputs import (
    available_previous_slices,
    non_empty_scope_slices,
)
from panorama_compliance.domain.delivery.rescind_reporting import (
    mark_unreported_rescinds_for_suspension_report,
    rescind_reporting_diagnostics,
)


@dataclass(frozen=True)
class PdfDeliveryResult:
    generated_paths: list[Path]
    uploaded_count: int
    cleanup_entries: list[str]
    suspension_totals: dict[str, int] | None = None
    rescind_diagnostics: dict[str, int] | None = None


def dry_run_report_candidates(
    *,
    report_type: str,
    frame: pl.DataFrame,
    school_labels: list[str],
    run_day: date,
    prev_business_day: date | None,
    reports_dir: Path,
    artifacts_root: Path,
    reference: SchoolReference,
    school_year_start_month: int,
) -> list[Path]:
    output_paths: list[Path] = []
    for label in school_labels:
        school_df = frame.filter(pl.col("school_label") == label)
        if report_type == "suspension":
            if prev_business_day is None:
                raise RuntimeError(
                    "Suspension dry-run candidate rendering requires previous business day."
                )
            active = school_df.filter(
                pl.col("compliant").is_null() | (pl.col("compliant") > run_day)
            )
            rescinded = school_df.filter(
                pl.col("compliant").is_not_null()
                & (pl.col("compliant") <= run_day)
                & (pl.col("compliant") > prev_business_day)
            )
            final_report = active.is_empty() and rescinded.is_empty()
        else:
            final_report = school_df.is_empty()
        paths = build_report_paths(
            output_root=reports_dir,
            artifacts_root=artifacts_root,
            report_type=report_type,
            school=str(label),
            run_date=run_day,
            secondary_labels=reference.secondary_labels,
            final_report=final_report,
            school_year_start_month=school_year_start_month,
        )
        output_paths.append(paths.pdf_path)
    return output_paths


def resolve_report_school_labels(
    *,
    frame: pl.DataFrame,
    scope: DeliveryScope,
    reference: SchoolReference,
    slice_tokens: set[str] | None,
) -> list[str]:
    labels = set(
        collect_scope_school_labels(
            scope=scope,
            reference=reference,
            allowed_slice_tokens=slice_tokens,
        )
    )
    if not labels:
        raise RuntimeError(
            f"Scope {scope.label} resolved to zero schools for PDF generation."
        )

    if "school_label" in frame.columns:
        frame_labels = (
            frame.select(pl.col("school_label").cast(pl.Utf8, strict=False))
            .drop_nulls()
            .unique()
            .to_series()
            .drop_nulls()
            .to_list()
        )
        labels.update(
            str(value).strip() for value in frame_labels if str(value).strip()
        )

    return sorted(labels, key=str.casefold)


def school_folder_resolver(reference: SchoolReference) -> Callable[[str], str | None]:
    return lambda school_label: resolve_sharepoint_folder_for_school(
        reference,
        school_label,
    )


def build_pdf_report_outputs(
    *,
    report_type: str,
    frame: pl.DataFrame,
    school_labels: list[str],
    run_day: date,
    candidate_previous_day: date | None,
    report_previous_day: date | None,
    reports_dir: Path,
    report_artifacts_root: Path,
    logo_path: Path,
    typst_bin: str,
    project_root: Path,
    reference: SchoolReference,
    privacy_notice_path: Path | None,
    school_year_start_month: int,
    sharepoint_settings,
    io_mode: IOMode,
    cleanup_sharepoint_pdfs: bool,
    retain_typst_artifacts: bool,
    verbose: bool,
) -> tuple[list[Path], int, list[str]]:
    generated_paths: list[Path]
    uploaded_count = 0
    cleanup_entries: list[str] = []
    resolver = school_folder_resolver(reference)

    if io_mode.dry_run:
        generated_paths = dry_run_report_candidates(
            report_type=report_type,
            frame=frame,
            school_labels=school_labels,
            run_day=run_day,
            prev_business_day=candidate_previous_day,
            reports_dir=reports_dir,
            artifacts_root=report_artifacts_root,
            reference=reference,
            school_year_start_month=school_year_start_month,
        )
        if cleanup_sharepoint_pdfs:
            if sharepoint_settings is None:
                raise RuntimeError(
                    "SharePoint cleanup preview requires the SharePoint output publisher."
                )
            cleanup_entries = preview_report_pdf_cleanup(
                sharepoint_settings,
                school_labels=school_labels,
                secondary_labels=reference.secondary_labels,
                terminal_cleanup_school_labels=_post_window_school_labels(
                    school_labels=school_labels,
                    reference=reference,
                    run_day=run_day,
                ),
                run_date=run_day,
                school_year_start_month=school_year_start_month,
                school_folder_resolver=resolver,
            )
        return generated_paths, uploaded_count, cleanup_entries

    try:
        report_outputs = render_report_outputs(
            report_type,
            frame,
            run_day,
            report_previous_day,
            reports_dir,
            report_artifacts_root,
            logo_path,
            typst_bin,
            project_root,
            False,
            False,
            retain_typst_artifacts,
            reference.secondary_labels,
            target_school_labels=school_labels,
            reference=reference,
            privacy_notice_path=privacy_notice_path,
            school_year_start_month=school_year_start_month,
            verbose=verbose,
        )
        generated_paths = [output.pdf_path for output in report_outputs]
        if io_mode.publish:
            if sharepoint_settings is None:
                raise RuntimeError(
                    "PDF publishing requires the SharePoint output publisher."
                )
            summary = publish_daily_outputs(
                sharepoint_settings,
                diff_outputs=[],
                report_outputs=report_outputs,
                secondary_labels=reference.secondary_labels,
                run_date=run_day,
                school_year_start_month=school_year_start_month,
                cleanup_report_pdfs=cleanup_sharepoint_pdfs,
                school_folder_resolver=resolver,
            )
            uploaded_count = len(summary.uploaded_urls)
            if cleanup_sharepoint_pdfs:
                cleanup_entries.extend(summary.deleted_overdue)
    finally:
        if not retain_typst_artifacts:
            cleanup_report_artifacts(report_artifacts_root, {report_type})

    return generated_paths, uploaded_count, cleanup_entries


def _compute_overdue_total(*, frame: pl.DataFrame) -> int:
    if "client_id" in frame.columns:
        return int(frame.select(pl.col("client_id").n_unique()).item())
    return int(frame.height)


def _compute_suspension_list_totals(
    *,
    frame: pl.DataFrame,
    run_day: date,
    prev_business_day: date,
) -> dict[str, int]:
    active_total = frame.filter(
        pl.col("compliant").is_null() | (pl.col("compliant") > run_day)
    ).height
    if "report_rescinded" in frame.columns:
        newly_rescinded_total = frame.filter(
            pl.col("compliant").is_not_null()
            & (pl.col("compliant") <= run_day)
            & (pl.col("compliant") >= prev_business_day)
            & pl.col("report_rescinded").fill_null(False)
        ).height
    else:
        newly_rescinded_total = frame.filter(
            pl.col("compliant").is_not_null()
            & (pl.col("compliant") <= run_day)
            & (pl.col("compliant") > prev_business_day)
        ).height
    return {
        "active_suspensions": int(active_total),
        "newly_rescinded": int(newly_rescinded_total),
    }


def write_overdue_pdf_outputs(
    *,
    source: str,
    active_by_slice: dict[str, pl.DataFrame],
    pear_state_dir: Path,
    run_date: str,
    run_day: date,
    previous_day: date | None,
    output_id: str,
    scope: DeliveryScope,
    reference: SchoolReference,
    reports_dir: Path,
    report_artifacts_root: Path,
    logo_path: Path,
    typst_bin: str,
    project_root: Path,
    privacy_notice_path: Path | None,
    school_year_start_month: int,
    sharepoint_settings,
    io_mode: IOMode,
    cleanup_sharepoint_pdfs: bool,
    retain_typst_artifacts: bool,
    verbose: bool,
    validation_summary: ValidationSummary,
    pass_log: Callable[[str], None],
) -> PdfDeliveryResult:
    if source == "panorama":
        overdue_df = pl.concat(list(active_by_slice.values()), how="vertical")
        report_slice_tokens = set(active_by_slice)
    else:
        try:
            pear_overdue_by_slice = _load_scoped_pear_state_frames(
                pear_state_dir=pear_state_dir,
                state_name="overdue_active",
                run_date=run_date,
                scope=scope,
                reference=reference,
            )
        except RuntimeError as exc:
            if not _scope_is_after_suspension_window(
                scope=scope,
                reference=reference,
                run_day=run_day,
            ):
                raise
            logging.info(
                "PEAR overdue PDF fallback: scope %s is after suspension_window_end "
                "for all selected schools; treating missing PEAR state as empty. "
                "Original error: %s",
                scope.label,
                exc,
            )
            pear_overdue_by_slice = _empty_pear_report_frames_for_scope(
                scope=scope,
                reference=reference,
                report_type="overdue",
            )
        overdue_df = pl.concat(list(pear_overdue_by_slice.values()), how="vertical")
        report_slice_tokens = set(pear_overdue_by_slice)

    overdue_df = ensure_school_label_column(overdue_df)
    overdue_total = _compute_overdue_total(frame=overdue_df)
    logging.info("Overdue list total for %s: overall=%s", scope.label, overdue_total)
    validate_report_delivery_contract(overdue_df, output_id=output_id)
    validation_summary.record_pass(
        rule_id=RULE_DELIVERY_CONTRACT_ID,
        message=f"delivery contract passed for {output_id}",
        log=pass_log,
    )
    overdue_school_labels = resolve_report_school_labels(
        frame=overdue_df,
        scope=scope,
        reference=reference,
        slice_tokens=report_slice_tokens,
    )

    generated_paths, uploaded_count, cleanup_entries = build_pdf_report_outputs(
        report_type="overdue",
        frame=overdue_df,
        school_labels=overdue_school_labels,
        run_day=run_day,
        candidate_previous_day=None,
        report_previous_day=previous_day,
        reports_dir=reports_dir,
        report_artifacts_root=report_artifacts_root,
        logo_path=logo_path,
        typst_bin=typst_bin,
        project_root=project_root,
        reference=reference,
        privacy_notice_path=privacy_notice_path,
        school_year_start_month=school_year_start_month,
        sharepoint_settings=sharepoint_settings,
        io_mode=io_mode,
        cleanup_sharepoint_pdfs=cleanup_sharepoint_pdfs,
        retain_typst_artifacts=retain_typst_artifacts,
        verbose=verbose,
    )
    return PdfDeliveryResult(
        generated_paths=generated_paths,
        uploaded_count=uploaded_count,
        cleanup_entries=cleanup_entries,
    )


def write_suspension_pdf_outputs(
    *,
    source: str,
    snapshot_by_slice: dict[str, pl.DataFrame],
    pear_state_dir: Path,
    pear_processed_dir: Path,
    pear_suspension_override: Path | None,
    run_date: str,
    run_day: date,
    previous_day: date | None,
    output_id: str,
    scope: DeliveryScope,
    reference: SchoolReference,
    compliance_history_dir: Path,
    state_store: StateStore | None,
    read_authoritative: bool,
    reports_dir: Path,
    report_artifacts_root: Path,
    logo_path: Path,
    typst_bin: str,
    project_root: Path,
    privacy_notice_path: Path | None,
    school_year_start_month: int,
    sharepoint_settings,
    io_mode: IOMode,
    cleanup_sharepoint_pdfs: bool,
    retain_typst_artifacts: bool,
    verbose: bool,
    validation_summary: ValidationSummary,
    warning_recorder: Callable[[RuleResult], None],
    pass_log: Callable[[str], None],
) -> PdfDeliveryResult:
    try:
        required_previous_day = require_previous_business_day(
            previous_business_day=previous_day,
            run_date=run_date,
            label=output_id,
        )
    except ValidationError as exc:
        validation_summary.record_failure(
            rule_id=RULE_PREVIOUS_BUSINESS_DAY_ID,
            message=str(exc),
            log=logging.error,
        )
        raise
    validation_summary.record_pass(
        rule_id=RULE_PREVIOUS_BUSINESS_DAY_ID,
        message=f"previous business day resolved for {output_id}",
        log=pass_log,
    )

    rescind_diagnostics_payload: dict[str, int] | None = None
    if source == "panorama":
        previous_date = required_previous_day.strftime("%Y%m%d")
        available_slices = available_previous_slices(
            read_authoritative=read_authoritative,
            compliance_history_dir=compliance_history_dir,
            state_store=state_store,
            previous_date=previous_date,
        )
        data_warning = previous_scope_data_file_warning(
            previous_date=previous_date,
            scope_label=scope.label,
            output_id=output_id,
            required_slices=non_empty_scope_slices(snapshot_by_slice),
            available_slices=available_slices,
            download_enabled=read_authoritative,
        )
        if data_warning is not None:
            warning_recorder(data_warning)
        else:
            validation_summary.record_pass(
                rule_id=RULE_PREVIOUS_SCOPE_DATA_ID,
                message=f"previous business day scope data files confirmed for {output_id}",
                log=pass_log,
            )
        suspension_df = pl.concat(list(snapshot_by_slice.values()), how="vertical")
        report_slice_tokens: set[str] | None = set(snapshot_by_slice)
    else:
        override_for_authoritative: pl.DataFrame | None = None
        validation_summary.record_pass(
            rule_id=RULE_PREVIOUS_SCOPE_DATA_ID,
            message=(
                "PEAR suspension report source does not require prior compliance_history "
                "scope-file availability checks"
            ),
            log=pass_log,
        )
        if pear_suspension_override is None:
            try:
                pear_suspension_by_slice = _load_scoped_pear_state_frames(
                    pear_state_dir=pear_state_dir,
                    state_name="suspension_operational",
                    run_date=run_date,
                    scope=scope,
                    reference=reference,
                )
            except RuntimeError as exc:
                if not _scope_is_after_suspension_window(
                    scope=scope,
                    reference=reference,
                    run_day=run_day,
                ):
                    raise
                logging.info(
                    "PEAR suspension PDF fallback: scope %s is after "
                    "suspension_window_end for all selected schools; treating "
                    "missing PEAR state as empty. Original error: %s",
                    scope.label,
                    exc,
                )
                pear_suspension_by_slice = _empty_pear_report_frames_for_scope(
                    scope=scope,
                    reference=reference,
                    report_type="suspension",
                )
        else:
            override_frame = pl.read_parquet(pear_suspension_override)
            override_scoped = apply_scope_filter(
                override_frame, scope=scope, reference=reference
            )
            override_scoped = _apply_wave_scope_filter(
                frame=override_scoped,
                scope=scope,
                reference=reference,
            )
            override_for_authoritative = override_scoped
            pear_suspension_by_slice = {"override": override_scoped}
            logging.info(
                "Using PEAR suspension override file for delivery: %s",
                pear_suspension_override,
            )

        suspension_df = pl.concat(
            list(pear_suspension_by_slice.values()), how="vertical"
        ).with_columns(
            pl.col("rescind_date").cast(pl.Date, strict=False).alias("compliant")
        )
        report_slice_tokens = (
            None
            if pear_suspension_override is not None
            else set(pear_suspension_by_slice)
        )
        previous_authoritative_by_slice = (
            _load_scoped_pear_authoritative_baseline_frames(
                pear_processed_dir=pear_processed_dir,
                run_date=required_previous_day.strftime("%Y%m%d"),
                scope=scope,
                reference=reference,
            )
        )
        previous_authoritative_df = (
            pl.concat(list(previous_authoritative_by_slice.values()), how="vertical")
            if previous_authoritative_by_slice
            else pl.DataFrame(schema={"client_id": pl.Utf8, "rescind_date": pl.Date})
        )
        suspension_df, unreported_rescinds = (
            mark_unreported_rescinds_for_suspension_report(
                current_frame=suspension_df,
                previous_authoritative_frame=previous_authoritative_df,
                run_day=run_day,
                prev_business_day=required_previous_day,
            )
        )
        rescind_diagnostics_payload = rescind_reporting_diagnostics(
            current_frame=suspension_df,
            previous_authoritative_frame=previous_authoritative_df,
            run_day=run_day,
            prev_business_day=required_previous_day,
        )
        logging.info(
            "PEAR suspension rescind filtering: unreported rescinds in [%s, %s] = %s",
            required_previous_day.isoformat(),
            run_day.isoformat(),
            unreported_rescinds,
        )
        logging.info(
            "PEAR suspension rescind diagnostics: transitions=%s "
            "date_shift_only=%s prior_active=%s current_active=%s",
            rescind_diagnostics_payload["rescinds_transition_count"],
            rescind_diagnostics_payload["rescinds_date_shift_only_count"],
            rescind_diagnostics_payload["prior_active_count"],
            rescind_diagnostics_payload["current_active_count"],
        )
        if override_for_authoritative is not None and io_mode.publish:
            if state_store is None:
                raise RuntimeError(
                    "PEAR suspension override promotion requires a state store."
                )
            promoted_authoritative_paths = write_pear_authoritative_suspension_outputs(
                suspension_operational=override_for_authoritative,
                run_date=run_date,
                output_dir=pear_processed_dir,
            )
            if promoted_authoritative_paths:
                settings = getattr(state_store, "settings", None)
                destinations = getattr(settings, "destinations", None)
                pear_processed_prefix = getattr(
                    destinations,
                    "pear_processed_prefix",
                    None,
                )
                if pear_processed_prefix is None or not pear_processed_prefix.strip():
                    raise RuntimeError(
                        "PEAR suspension override promotion requires "
                        "io.adls.destinations.pear_processed_prefix"
                    )
                state_store.upload_paths(
                    paths=promoted_authoritative_paths,
                    prefix=pear_processed_prefix,
                )
                logging.info(
                    "Promoted PEAR suspension override to official "
                    "suspension-operational baseline (%s file(s))",
                    len(promoted_authoritative_paths),
                )

    suspension_df = ensure_school_label_column(suspension_df)
    suspension_totals = _compute_suspension_list_totals(
        frame=suspension_df,
        run_day=run_day,
        prev_business_day=required_previous_day,
    )
    logging.info(
        "Suspension list totals for %s: active=%s newly_rescinded=%s",
        scope.label,
        suspension_totals["active_suspensions"],
        suspension_totals["newly_rescinded"],
    )
    validate_report_delivery_contract(suspension_df, output_id=output_id)
    validation_summary.record_pass(
        rule_id=RULE_DELIVERY_CONTRACT_ID,
        message=f"delivery contract passed for {output_id}",
        log=pass_log,
    )
    suspension_school_labels = resolve_report_school_labels(
        frame=suspension_df,
        scope=scope,
        reference=reference,
        slice_tokens=report_slice_tokens,
    )

    generated_paths, uploaded_count, cleanup_entries = build_pdf_report_outputs(
        report_type="suspension",
        frame=suspension_df,
        school_labels=suspension_school_labels,
        run_day=run_day,
        candidate_previous_day=required_previous_day,
        report_previous_day=required_previous_day,
        reports_dir=reports_dir,
        report_artifacts_root=report_artifacts_root,
        logo_path=logo_path,
        typst_bin=typst_bin,
        project_root=project_root,
        reference=reference,
        privacy_notice_path=privacy_notice_path,
        school_year_start_month=school_year_start_month,
        sharepoint_settings=sharepoint_settings,
        io_mode=io_mode,
        cleanup_sharepoint_pdfs=cleanup_sharepoint_pdfs,
        retain_typst_artifacts=retain_typst_artifacts,
        verbose=verbose,
    )
    return PdfDeliveryResult(
        generated_paths=generated_paths,
        uploaded_count=uploaded_count,
        cleanup_entries=cleanup_entries,
        suspension_totals=suspension_totals,
        rescind_diagnostics=rescind_diagnostics_payload,
    )
