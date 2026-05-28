from __future__ import annotations

from pathlib import Path

import polars as pl

from panorama_compliance.domain.pear.state._common import (
    _STATE_OUTPUT_PATTERN,
    _WAVE_SLICED_PROCESSED_PATTERN,
    PROCESSED_REPORT_SUSPENSION_OPERATIONAL,
    REPORT_SUSPENSION_OPERATIONAL,
    STATE_NAMES,
)
from panorama_compliance.domain.pear.state.reconcile import _project_state_columns
from panorama_compliance.ingest.combine import wave_to_token
from panorama_compliance.schema import ValidationError


def write_pear_state_outputs(
    *,
    frames: dict[str, pl.DataFrame],
    run_date: str,
    output_dir: Path,
    formats: tuple[str, ...] = ("parquet",),
) -> list[Path]:
    requested_formats = {fmt.lower() for fmt in formats}
    if not requested_formats:
        raise ValueError("At least one output format is required")

    valid_formats = {"parquet", "xlsx", "csv"}
    invalid_formats = sorted(requested_formats - valid_formats)
    if invalid_formats:
        raise ValueError(f"Unsupported output format(s): {invalid_formats}")

    output_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for state_name in STATE_NAMES:
        frame = frames.get(state_name)
        if frame is None or frame.is_empty():
            continue
        for wave_key, wave_frame in frame.partition_by("wave", as_dict=True).items():
            if wave_key is None or not str(wave_key).strip():
                raise ValidationError(
                    f"{state_name}: missing wave value in output rows"
                )
            slice_token = wave_to_token(str(wave_key))
            output_base = output_dir / f"{run_date}_pear_{slice_token}_{state_name}"
            if "parquet" in requested_formats:
                parquet_path = output_base.with_suffix(".parquet")
                wave_frame.write_parquet(parquet_path)
                written.append(parquet_path)
            if "xlsx" in requested_formats:
                xlsx_path = output_base.with_suffix(".xlsx")
                wave_frame.write_excel(xlsx_path)
                written.append(xlsx_path)
            if "csv" in requested_formats:
                csv_path = output_base.with_suffix(".csv")
                wave_frame.write_csv(csv_path)
                written.append(csv_path)
    return written


def write_pear_authoritative_suspension_outputs(
    *,
    suspension_operational: pl.DataFrame,
    run_date: str,
    output_dir: Path,
) -> list[Path]:
    if suspension_operational.is_empty():
        return []
    output_dir.mkdir(parents=True, exist_ok=True)
    projected = _project_state_columns(
        suspension_operational,
        state_name=REPORT_SUSPENSION_OPERATIONAL,
    )
    written: list[Path] = []
    for wave_key, wave_frame in projected.partition_by("wave", as_dict=True).items():
        if wave_key is None or not str(wave_key).strip():
            raise ValidationError(
                "suspension_operational baseline: missing wave value in output rows"
            )
        slice_token = wave_to_token(str(wave_key))
        path = output_dir / (
            f"{run_date}_pear_{PROCESSED_REPORT_SUSPENSION_OPERATIONAL}_{slice_token}.parquet"
        )
        wave_frame.write_parquet(path)
        written.append(path)
    return written


def discover_latest_pear_state_by_slice(
    pear_state_dir: Path,
    *,
    state_name: str,
    run_date: str | None = None,
) -> dict[str, Path]:
    if state_name not in STATE_NAMES:
        raise ValueError(
            f"Unsupported PEAR state_name={state_name!r}; expected one of {STATE_NAMES}"
        )

    latest: dict[str, tuple[str, Path]] = {}
    for path in pear_state_dir.glob(f"*_pear_*_{state_name}.parquet"):
        match = _STATE_OUTPUT_PATTERN.match(path.name)
        if not match:
            continue
        date_token = match.group("date")
        if run_date is not None and date_token > run_date:
            continue
        slice_token = match.group("slice")
        existing = latest.get(slice_token)
        if existing is None or date_token > existing[0]:
            latest[slice_token] = (date_token, path)
    return {slice_token: path for slice_token, (_, path) in sorted(latest.items())}


def _should_replace_latest(
    *,
    existing: tuple[str, int, Path] | None,
    candidate_date: str,
    candidate_priority: int,
) -> bool:
    if existing is None:
        return True
    existing_date, existing_priority, _existing_path = existing
    if candidate_date != existing_date:
        return candidate_date > existing_date
    return candidate_priority > existing_priority


def discover_latest_pear_authoritative_baseline_by_slice(
    baseline_dir: Path,
    *,
    run_date: str | None = None,
    exact_run_date: bool = False,
) -> dict[str, Path]:
    if exact_run_date and run_date is None:
        raise ValueError("exact_run_date=True requires run_date")
    latest: dict[str, tuple[str, int, Path]] = {}
    # Preferred canonical processed baseline naming:
    # YYYYMMDD_pear_suspension_operational_<slice>.parquet
    for path in baseline_dir.glob(
        f"*_pear_{PROCESSED_REPORT_SUSPENSION_OPERATIONAL}_*.parquet"
    ):
        match = _WAVE_SLICED_PROCESSED_PATTERN.match(path.name)
        if not match:
            continue
        if match.group("report") != PROCESSED_REPORT_SUSPENSION_OPERATIONAL:
            continue
        date_token = match.group("date")
        if run_date is not None:
            if exact_run_date and date_token != run_date:
                continue
            if not exact_run_date and date_token > run_date:
                continue
        slice_token = match.group("slice")
        existing = latest.get(slice_token)
        if _should_replace_latest(
            existing=existing,
            candidate_date=date_token,
            candidate_priority=2,
        ):
            latest[slice_token] = (date_token, 2, path)

    # Also accept state-style naming when available:
    # YYYYMMDD_pear_<slice>_suspension_operational.parquet
    for path in baseline_dir.glob(f"*_pear_*_{REPORT_SUSPENSION_OPERATIONAL}.parquet"):
        match = _STATE_OUTPUT_PATTERN.match(path.name)
        if not match:
            continue
        if match.group("state") != REPORT_SUSPENSION_OPERATIONAL:
            continue
        date_token = match.group("date")
        if run_date is not None:
            if exact_run_date and date_token != run_date:
                continue
            if not exact_run_date and date_token > run_date:
                continue
        slice_token = match.group("slice")
        existing = latest.get(slice_token)
        if _should_replace_latest(
            existing=existing,
            candidate_date=date_token,
            candidate_priority=1,
        ):
            latest[slice_token] = (date_token, 1, path)
    return {slice_token: path for slice_token, (_, _, path) in sorted(latest.items())}


__all__ = [
    "write_pear_state_outputs",
    "write_pear_authoritative_suspension_outputs",
    "discover_latest_pear_state_by_slice",
    "discover_latest_pear_authoritative_baseline_by_slice",
]
