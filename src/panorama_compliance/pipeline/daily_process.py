from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import polars as pl

from panorama_compliance.compliance_history import (
    derive_active_noncompliant,
    discover_latest_compliance_history_by_slice,
    project_schema_columns,
    read_compliance_history_frame,
    update_compliance_history,
    write_output_base,
)
from panorama_compliance.diff import run_daily_diff_from_compliance_history
from panorama_compliance.ingest import (
    combine_standardized_files,
    standardize_input_files,
)
from panorama_compliance.io.adls import AdlsSettings
from panorama_compliance.io.sharepoint_settings import SharePointSettings
from panorama_compliance.io.type_inference import infer_file_types
from panorama_compliance.models import AlertRecord, FileManifest, ReportOutput
from panorama_compliance.pipeline.run_artifacts import stage_summary, utc_now
from panorama_compliance.pipeline.daily_publish import publish_stage
from panorama_compliance.reference import (
    SchoolReference,
    collect_scope_values,
)
from panorama_compliance.reports.service import (
    cleanup_report_artifacts,
    render_report_outputs,
)
from panorama_compliance.schema import ValidationError
from panorama_compliance.validation import (
    FAIL_STATUS,
    ParseFailureCounter,
    RuleResult,
    RULE_PARSE_COUNTERS_ID,
    RULE_PREVIOUS_BUSINESS_DAY_ID,
    RULE_TEMPORAL_BOUNDS_ID,
    ValidationSummary,
    all_rule_ids,
    aggregate_parse_counters,
    ensure_school_label_column,
    normalize_level_filter_values,
    normalize_school_id_filter_values,
    normalize_wave_filter_values,
    parse_counter_alerts,
    require_previous_business_day,
    run_update_state_validations,
    validation_line,
)


COMBINED_PATTERN = "{date}_panorama_{slice}_noncompliant"
DEFAULT_SCHEMA_ROOT = Path(__file__).resolve().parents[3] / "schema"


@dataclass(frozen=True)
class ProcessStageResult:
    manifests: list[FileManifest]
    datasets: dict[str, pl.DataFrame]
    report_outputs: list[ReportOutput]
    file_outputs: list[Path]
    current_df: pl.DataFrame
    previous_df: pl.DataFrame | None
    runtime_alerts: list[AlertRecord]
    stage_summaries: dict[str, dict[str, Any]]
    adls_processed_uploads: list[str]
    adls_derived_uploads: list[str]
    sharepoint_uploaded_urls: list[str]
    sharepoint_deleted_overdue: list[str]
    parse_counters: list[ParseFailureCounter]
    parse_counter_totals: dict[str, dict[str, int]]


def _safe_read(path: Path, *, schema_root: Path | None = None) -> pl.DataFrame:
    _ = schema_root or DEFAULT_SCHEMA_ROOT
    suffix = path.suffix.lower()
    if suffix == ".parquet":
        return pl.read_parquet(path)
    if suffix == ".csv":
        return pl.read_csv(
            path,
            schema_overrides={"client_id": pl.String()},
            infer_schema_length=1000,
        )
    raise ValueError(
        f"Unsupported file format for pipeline dataset reads: {path} "
        "(expected .parquet or .csv)"
    )


def _slice_from_path(path: Path) -> str:
    name = path.name
    if "_panorama_" not in name or "_noncompliant" not in name:
        return "unknown"
    return name.split("_panorama_", 1)[1].split("_noncompliant", 1)[0]


def _find_preferred(paths: list[Path]) -> Path | None:
    if not paths:
        return None
    parquet = [path for path in paths if path.suffix.lower() == ".parquet"]
    if parquet:
        return sorted(parquet)[0]
    return sorted(paths)[0]


def _collect_written_outputs(
    output_path: Path, *, formats: tuple[str, ...]
) -> list[Path]:
    base = output_path.with_suffix("")
    requested = {fmt.lower() for fmt in formats}
    candidates: list[Path] = []
    if "parquet" in requested:
        candidates.append(base.with_suffix(".parquet"))
    if "xlsx" in requested:
        candidates.append(base.with_suffix(".xlsx"))
    if "csv" in requested:
        candidates.append(base.with_suffix(".csv"))
    if not candidates:
        return [output_path]
    discovered = [path for path in candidates if path.exists()]
    if discovered:
        return discovered
    return [output_path]


def process_stage(
    *,
    run_day: date,
    run_date: str,
    previous_day: date | None,
    previous_date: str | None,
    project_root: Path,
    input_raw: Path,
    standardized_dir: Path,
    combined_dir: Path,
    compliance_history_dir: Path,
    diff_dir: Path,
    reports_dir: Path,
    artifacts_root: Path,
    schema_root: Path,
    reference: SchoolReference,
    outputs_cfg: dict[str, Any],
    options: Any,
    adls_settings: AdlsSettings,
    sharepoint_settings: SharePointSettings,
    logo_path: Path,
    typst_bin: str,
    privacy_notice_path: Path | None,
    school_year_start_month: int = 9,
) -> ProcessStageResult:
    process_started = utc_now()
    runtime_alerts: list[AlertRecord] = []
    parse_counters: list[ParseFailureCounter] = []
    validation_summary = ValidationSummary(tracked_rule_ids=all_rule_ids())
    configured_formats = outputs_cfg.get("formats", {})
    if isinstance(configured_formats, dict):
        ignored_format_overrides: list[str] = []
        for stream_key in ("combined", "compliance_history", "diffs"):
            stream_formats = configured_formats.get(stream_key)
            if not isinstance(stream_formats, list):
                continue
            normalized = {str(value).lower() for value in stream_formats}
            if normalized and normalized != {"parquet"}:
                ignored_format_overrides.append(f"{stream_key}={stream_formats}")
        if ignored_format_overrides:
            logging.info(
                "Ignoring outputs.formats overrides for internal pipeline outputs "
                "(parquet-only): %s",
                ", ".join(sorted(ignored_format_overrides)),
            )

    raw_files = sorted(list(input_raw.glob("*.xls")) + list(input_raw.glob("*.xlsx")))
    manifests = infer_file_types(raw_files, fix_extensions=False)

    standardized_entries = standardize_input_files(
        input_dir=input_raw,
        standardized_dir=standardized_dir,
        run_date=run_date,
        reference=reference,
        schema_root=schema_root,
        strict_headers=options.strict_headers,
    )
    logging.info("Standardized %s files", len(standardized_entries))

    combined_formats = ("parquet",)
    try:
        allowed_waves, allowed_levels = collect_scope_values(reference)
        normalized_school_ids = normalize_school_id_filter_values(options.school_ids)
        normalized_levels = normalize_level_filter_values(
            options.levels,
            arg_name="--level",
            allowed_values=allowed_levels,
        )
        normalized_waves = normalize_wave_filter_values(
            options.waves,
            arg_name="--wave",
            allowed_values=allowed_waves,
        )
    except ValueError as exc:
        raise ValidationError(str(exc)) from exc

    written_combined = combine_standardized_files(
        entries=standardized_entries,
        run_date=run_date,
        output_dir=combined_dir,
        schema_root=schema_root,
        reference=reference,
        school_ids=normalized_school_ids,
        levels=normalized_levels,
        waves=normalized_waves,
        formats=combined_formats,
        parse_counters_sink=parse_counters,
    )

    current_candidates: dict[str, Path] = {}
    for _, paths in written_combined.items():
        preferred = _find_preferred(paths)
        if preferred is None:
            continue
        current_candidates[_slice_from_path(preferred)] = preferred

    if not current_candidates:
        raise RuntimeError("No combined candidate outputs generated")

    compliance_history_outputs: list[Path] = []
    latest_compliance_history_by_slice: dict[str, Path] = {}
    compliance_history_formats = ("parquet",)
    emitted_compliance_history_slices: list[str] = []
    for slice_token, current_path in sorted(current_candidates.items()):
        written = update_compliance_history(
            run_date=run_date,
            current_combined_path=current_path,
            compliance_history_dir=compliance_history_dir,
            schema_root=schema_root,
            formats=compliance_history_formats,
            allow_additions=options.allow_compliance_history_additions,
            strict_headers=options.strict_headers,
        )
        compliance_history_outputs.extend(written)
        preferred = _find_preferred(written)
        if preferred is not None:
            latest_compliance_history_by_slice[slice_token] = preferred
            emitted_compliance_history_slices.append(slice_token)
            logging.debug(
                "Compliance History updated for %s -> %s files",
                slice_token,
                len(written),
            )
        else:
            logging.debug(
                "Compliance History unchanged for %s; no new snapshot emitted",
                slice_token,
            )

    fallback_compliance_history_slices: list[str] = []
    if len(latest_compliance_history_by_slice) < len(current_candidates):
        discovered_compliance_histories = discover_latest_compliance_history_by_slice(
            compliance_history_dir,
            run_date=run_date,
        )
        for slice_token in sorted(current_candidates):
            if slice_token in latest_compliance_history_by_slice:
                continue
            fallback = discovered_compliance_histories.get(slice_token)
            if fallback is not None:
                latest_compliance_history_by_slice[slice_token] = fallback
                fallback_compliance_history_slices.append(slice_token)

    logging.info(
        "Compliance History merge complete: slices=%s, snapshots_emitted=%s, snapshots_reused=%s",
        len(current_candidates),
        len(emitted_compliance_history_slices),
        len(fallback_compliance_history_slices),
    )
    if fallback_compliance_history_slices:
        logging.info(
            "Reused existing compliance_history snapshots for unchanged slices: %s",
            ", ".join(sorted(fallback_compliance_history_slices)),
        )

    combined_outputs: list[Path] = []
    current_combined: dict[str, Path] = {}
    compliance_history_frames_by_slice: dict[str, pl.DataFrame] = {}
    combined_output_count = 0
    for slice_token, compliance_history_path in sorted(
        latest_compliance_history_by_slice.items()
    ):
        compliance_history_df = read_compliance_history_frame(
            compliance_history_path,
            schema_root=schema_root,
            strict_headers=options.strict_headers,
            parse_counters_sink=parse_counters,
        )
        compliance_history_frames_by_slice[slice_token] = compliance_history_df
        try:
            temporal_results = run_update_state_validations(
                stage="U-E",
                frame=compliance_history_df,
                run_day=run_day,
                label=f"compliance_history {slice_token}",
            )
        except ValidationError as exc:
            logging.error(
                "%s",
                validation_line(
                    status=FAIL_STATUS,
                    rule_id=RULE_TEMPORAL_BOUNDS_ID,
                    message=str(exc),
                ),
            )
            raise
        if not temporal_results:
            validation_summary.record_pass(
                rule_id=RULE_TEMPORAL_BOUNDS_ID,
                message=f"temporal bounds passed for compliance_history {slice_token}",
                log=logging.info,
            )
        else:
            for result in temporal_results:
                validation_summary.record_warning(result, log=logging.warning)
                runtime_alerts.append(
                    AlertRecord(
                        code=result.code,
                        level=result.severity,
                        message=result.message,
                        context=result.context,
                    )
                )
        active_df = derive_active_noncompliant(
            compliance_history_df, as_of_date=run_day
        )
        projected = project_schema_columns(
            active_df,
            schema_root=schema_root,
            dataset_id="processed.panorama.noncompliant",
        )
        output_base = combined_dir / COMBINED_PATTERN.format(
            date=run_date,
            slice=slice_token,
        )
        written = write_output_base(
            projected,
            output_base=output_base,
            formats=combined_formats,
        )
        combined_outputs.extend(written)
        combined_output_count += len(written)
        preferred = _find_preferred(written)
        if preferred is not None:
            current_combined[slice_token] = preferred
        logging.debug(
            "Combined rebuilt from compliance_history for %s -> %s files",
            slice_token,
            len(written),
        )

    logging.info(
        "Combined rebuild complete: slices=%s, output_files=%s",
        len(current_combined),
        combined_output_count,
    )

    if not current_combined:
        raise RuntimeError("No combined outputs generated from compliance_history")

    diff_outputs: list[Path] = []
    if options.derive_diff_enabled and previous_date:
        validation_summary.record_pass(
            rule_id=RULE_PREVIOUS_BUSINESS_DAY_ID,
            message="previous business day resolved for integrated daily diff derivation",
            log=logging.info,
        )
        diff_formats = ("parquet",)
        for slice_token, compliance_history_path in sorted(
            latest_compliance_history_by_slice.items()
        ):
            result = run_daily_diff_from_compliance_history(
                compliance_history_path=compliance_history_path,
                run_date=run_date,
                previous_date=previous_date,
                output_dir=diff_dir,
                schema_root=schema_root,
                enforce_subset=True,
                formats=diff_formats,
                strict_headers=options.strict_headers,
            )
            diff_outputs.extend(
                _collect_written_outputs(result.output_path, formats=diff_formats)
            )
            logging.info(
                "Diff %s (from compliance_history): became_compliant=%s current_only=%s",
                slice_token,
                result.became_compliant_rows,
                result.current_only_rows,
            )
    elif options.derive_diff_enabled:
        result = AlertRecord(
            code="missing_previous_business_day",
            level="warning",
            message=f"Daily diff requested but previous business day is unavailable for {run_date}",
            context={"run_date": run_date},
        )
        runtime_alerts.append(result)
        validation_summary.record_warning(
            RuleResult(
                rule_id=RULE_PREVIOUS_BUSINESS_DAY_ID,
                code=result.code,
                severity="warning",
                message=result.message,
                context=result.context,
            ),
            log=logging.warning,
        )

    if options.allow_compliance_history_additions:
        runtime_alerts.append(
            AlertRecord(
                code="compliance_history_additions_allowed",
                level="warning",
                message="Compliance History additions are allowed for this run; normal hard-fail protection is bypassed.",
                context={"run_date": run_date},
            )
        )

    report_outputs: list[ReportOutput] = []
    attempted_report_types: set[str] = set()
    try:
        if options.derive_overdue_report_enabled:
            attempted_report_types.add("overdue")
            for _, combined_path in sorted(current_combined.items()):
                overdue_df = ensure_school_label_column(
                    _safe_read(combined_path, schema_root=schema_root)
                )
                report_outputs.extend(
                    render_report_outputs(
                        "overdue",
                        overdue_df,
                        run_day,
                        previous_day,
                        reports_dir,
                        artifacts_root,
                        logo_path,
                        typst_bin,
                        project_root,
                        options.no_compile,
                        options.prune_history,
                        options.keep_typst_artifacts,
                        reference.secondary_labels,
                        reference=reference,
                        privacy_notice_path=privacy_notice_path,
                        school_year_start_month=school_year_start_month,
                        verbose=options.verbose,
                    )
                )

        if options.derive_suspension_report_enabled:
            attempted_report_types.add("suspension")
            try:
                required_previous_day = require_previous_business_day(
                    previous_business_day=previous_day,
                    run_date=run_date,
                    label="suspension report generation",
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
                message="previous business day resolved for suspension report derivation",
                log=logging.info,
            )
            for _, compliance_history_df in sorted(
                compliance_history_frames_by_slice.items()
            ):
                suspension_df = ensure_school_label_column(compliance_history_df)
                report_outputs.extend(
                    render_report_outputs(
                        "suspension",
                        suspension_df,
                        run_day,
                        required_previous_day,
                        reports_dir,
                        artifacts_root,
                        logo_path,
                        typst_bin,
                        project_root,
                        options.no_compile,
                        options.prune_history,
                        options.keep_typst_artifacts,
                        reference.secondary_labels,
                        reference=reference,
                        privacy_notice_path=privacy_notice_path,
                        school_year_start_month=school_year_start_month,
                        verbose=options.verbose,
                    )
                )
    finally:
        if (
            attempted_report_types
            and not options.no_compile
            and not options.keep_typst_artifacts
        ):
            cleanup_report_artifacts(artifacts_root, attempted_report_types)

    derived_stage_outputs = sorted(set(diff_outputs + compliance_history_outputs))
    publish_result = publish_stage(
        run_day=run_day,
        adls_settings=adls_settings,
        sharepoint_settings=sharepoint_settings,
        reference=reference,
        schema_root=schema_root,
        combined_outputs=combined_outputs,
        compliance_history_outputs=compliance_history_outputs,
        diff_outputs=diff_outputs,
        report_outputs=report_outputs,
        adls_upload_combined_enabled=options.adls_upload_combined_enabled,
        adls_upload_compliance_history_enabled=(
            options.adls_upload_compliance_history_enabled
        ),
        adls_upload_diff_enabled=options.adls_upload_diff_enabled,
        sharepoint_publish_diff_enabled=options.sharepoint_publish_diff_enabled,
        sharepoint_publish_overdue_pdf_enabled=(
            options.sharepoint_publish_overdue_pdf_enabled
        ),
        sharepoint_publish_suspension_pdf_enabled=(
            options.sharepoint_publish_suspension_pdf_enabled
        ),
        sharepoint_cleanup_pdfs_enabled=options.sharepoint_cleanup_pdfs_enabled,
        school_year_start_month=school_year_start_month,
    )

    current_frames = [
        _safe_read(path, schema_root=schema_root) for path in current_combined.values()
    ]
    current_df = (
        pl.concat(current_frames, how="vertical") if current_frames else pl.DataFrame()
    )

    previous_df: pl.DataFrame | None = None
    if previous_day is not None:
        previous_frames = []
        for frame in compliance_history_frames_by_slice.values():
            previous_frames.append(
                derive_active_noncompliant(frame, as_of_date=previous_day)
            )
        if previous_frames:
            previous_df = pl.concat(previous_frames, how="vertical")

    datasets = {
        path.name: _safe_read(path, schema_root=schema_root)
        for path in current_combined.values()
    }
    for path in diff_outputs + compliance_history_outputs:
        datasets[path.name] = _safe_read(path, schema_root=schema_root)

    parse_alert_results = parse_counter_alerts(parse_counters)
    if parse_alert_results:
        for result in parse_alert_results:
            validation_summary.record_warning(result, log=logging.warning)
            runtime_alerts.append(
                AlertRecord(
                    code=result.code,
                    level=result.severity,
                    message=result.message,
                    context=result.context,
                )
            )
    parse_pass_count = max(len(parse_counters) - len(parse_alert_results), 0)
    validation_summary.record_pass_count(
        rule_id=RULE_PARSE_COUNTERS_ID,
        count=parse_pass_count,
        message=(
            f"date parse counters passed for {parse_pass_count} field-stream check(s)"
        ),
        log=logging.info,
    )
    parse_counter_totals = aggregate_parse_counters(parse_counters)

    report_paths = [output.pdf_path for output in report_outputs]
    file_outputs = sorted(set(combined_outputs + derived_stage_outputs + report_paths))

    process_ended = utc_now()
    stage_summaries = {
        "process": stage_summary(
            status="success",
            started_at=process_started,
            ended_at=process_ended,
            observed_input_count=len(raw_files),
            standardized_count=len(standardized_entries),
            slice_count=len(current_combined),
            combined_rows=current_df.height,
            compliance_history_output_count=len(compliance_history_outputs),
            diff_output_count=len(diff_outputs),
            report_output_count=len(report_outputs),
            parse_failure_totals=parse_counter_totals,
            validation=validation_summary.as_dict(),
        ),
        **publish_result.stage_summaries,
    }

    return ProcessStageResult(
        manifests=manifests,
        datasets=datasets,
        report_outputs=report_outputs,
        file_outputs=file_outputs,
        current_df=current_df,
        previous_df=previous_df,
        runtime_alerts=runtime_alerts,
        stage_summaries=stage_summaries,
        adls_processed_uploads=publish_result.adls_processed_uploads,
        adls_derived_uploads=publish_result.adls_derived_uploads,
        sharepoint_uploaded_urls=publish_result.sharepoint_uploaded_urls,
        sharepoint_deleted_overdue=publish_result.sharepoint_deleted_overdue,
        parse_counters=parse_counters,
        parse_counter_totals=parse_counter_totals,
    )
