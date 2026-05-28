from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import polars as pl
from azure.storage.filedatalake import FileSystemClient

from ispa_daily_workflow.domain.pear.intake import (
    REPORT_OVERDUE,
    REPORT_SUSPENSION,
    REPORT_SUSPENSION_VS_OVERDUE,
)
from ispa_daily_workflow.ingest.combine import wave_to_token
from ispa_daily_workflow.io.adls import upload_file


@dataclass(frozen=True)
class _ProcessedFile:
    source_file: Path
    report_type: str
    report_date: date
    landing_output: Path | None
    processed_output: Path | None
    landing_rows: int
    processed_rows: int
    no_action_rows: int
    warning_count: int
    warnings: tuple[str, ...]
    processed_outputs: tuple[Path, ...] = ()


def _warn_overwrite(path: Path, source_file: Path, *, level: str = "warning") -> None:
    message = "Canonical filename collision for %s; overwriting with %s"
    if level == "debug":
        logging.debug(message, path.name, source_file.name)
    elif level == "info":
        logging.info(message, path.name, source_file.name)
    else:
        logging.warning(message, path.name, source_file.name)


def _report_name_for_processed_output(*, report_type: str) -> str:
    if report_type == REPORT_SUSPENSION:
        return "suspension_list"
    if report_type == REPORT_SUSPENSION_VS_OVERDUE:
        return "suspension_vs_overdue"
    if report_type == REPORT_OVERDUE:
        return "overdue_list"
    raise ValueError(f"Unsupported PEAR report_type={report_type!r}")


def _reference_scope_frame(reference) -> pl.DataFrame:
    rows: list[list[str]] = []
    for school_id, record in sorted(reference.by_id.items()):
        wave_value = str(record.wave or "").strip().upper()
        level_value = str(record.level or "").strip().upper()
        if not school_id or not wave_value or not level_value:
            continue
        rows.append([str(school_id), wave_value, level_value])
    return pl.DataFrame(
        rows,
        schema=["school_id", "wave", "level"],
        orient="row",
    )


def _empty_wave_tokens_for_report(
    *,
    report_type: str,
    canonical_filename: str,
    reference,
) -> list[str]:
    allowed_levels: set[str] | None = None
    if report_type == REPORT_SUSPENSION:
        lower_name = canonical_filename.lower()
        if "_suspension_list_elementary." in lower_name:
            allowed_levels = {"ELEMENTARY"}
        elif "_suspension_list_secondary." in lower_name:
            allowed_levels = {"SECONDARY"}

    tokens: set[str] = set()
    for record in reference.by_id.values():
        wave_value = str(record.wave or "").strip()
        level_value = str(record.level or "").strip().upper()
        if not wave_value:
            continue
        if allowed_levels is not None and level_value not in allowed_levels:
            continue
        tokens.add(wave_to_token(wave_value))
    return sorted(tokens)


def _partition_processed_frame_by_wave(
    *,
    frame: pl.DataFrame,
    report_type: str,
    canonical_filename: str,
    reference,
    source_file: Path,
) -> dict[str, pl.DataFrame]:
    if frame.is_empty():
        tokens = _empty_wave_tokens_for_report(
            report_type=report_type,
            canonical_filename=canonical_filename,
            reference=reference,
        )
        if not tokens:
            raise ValueError(
                f"{source_file.name}: unable to resolve wave partitions for empty "
                f"processed {report_type} frame"
            )
        return {token: frame.clone() for token in tokens}

    scope = _reference_scope_frame(reference).select("school_id", "wave")
    scoped = frame.with_columns(
        pl.col("school_id")
        .cast(pl.Utf8, strict=False)
        .str.strip_chars()
        .alias("school_id")
    ).join(scope, on="school_id", how="left")
    unresolved = (
        scoped.filter(pl.col("wave").is_null())
        .select("school_id")
        .unique()
        .sort("school_id")
    )
    if unresolved.height:
        unresolved_ids = ", ".join(unresolved.get_column("school_id").to_list())
        raise ValueError(
            f"{source_file.name}: processed rows missing school_reference wave mapping "
            f"for school_id={unresolved_ids}"
        )

    partitions: dict[str, pl.DataFrame] = {}
    for wave_key, wave_frame in scoped.partition_by("wave", as_dict=True).items():
        if wave_key is None or not str(wave_key).strip():
            raise ValueError(
                f"{source_file.name}: processed rows contained blank wave after mapping"
            )
        token = wave_to_token(str(wave_key))
        partitions[token] = wave_frame.drop("wave")
    return dict(sorted(partitions.items()))


def _processed_wave_filename(
    *,
    report_date: date,
    report_type: str,
    slice_token: str,
) -> str:
    date_token = report_date.strftime("%Y%m%d")
    report_name = _report_name_for_processed_output(report_type=report_type)
    return f"{date_token}_pear_{report_name}_{slice_token}.parquet"


def _processed_outputs_for_entry(entry: _ProcessedFile) -> tuple[Path, ...]:
    if entry.processed_outputs:
        return entry.processed_outputs
    if entry.processed_output is not None:
        return (entry.processed_output,)
    return ()


def _resolve_optional_prefix(
    *,
    configured: str | None,
    override: str | None,
    label: str,
) -> str:
    if override is not None:
        value = override.strip()
        if not value:
            raise ValueError(f"{label} override cannot be empty")
        return value
    if configured is None or not configured.strip():
        raise ValueError(
            f"{label} is required for ADLS upload but is not configured. "
            "Set it in profile/config.yaml or pass an explicit override."
        )
    return configured.strip()


def _write_outputs(
    *,
    processed_files: list[_ProcessedFile],
    dry_run: bool,
    upload_to_adls: bool,
    file_system_client: FileSystemClient | None,
    landing_prefix: str | None,
    processed_prefix: str | None,
) -> tuple[list[Path], list[str]]:
    written_paths: list[Path] = []
    uploaded_paths: list[str] = []

    if dry_run:
        return written_paths, uploaded_paths

    for entry in processed_files:
        if entry.landing_output is not None:
            written_paths.append(entry.landing_output)
            if upload_to_adls:
                assert file_system_client is not None
                assert landing_prefix is not None
                remote_path = f"{landing_prefix}/{entry.landing_output.name}"
                upload_file(file_system_client, entry.landing_output, remote_path)
                uploaded_paths.append(remote_path)

        for processed_output in _processed_outputs_for_entry(entry):
            written_paths.append(processed_output)
            if upload_to_adls:
                assert file_system_client is not None
                assert processed_prefix is not None
                remote_path = f"{processed_prefix}/{processed_output.name}"
                upload_file(file_system_client, processed_output, remote_path)
                uploaded_paths.append(remote_path)

    return written_paths, uploaded_paths
