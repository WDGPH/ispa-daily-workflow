from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import polars as pl

from ispa_daily_workflow.compliance_history import (
    discover_compliance_history_by_slice_for_date,
    discover_latest_compliance_history_by_slice,
)
from ispa_daily_workflow.ingest.combine import wave_to_token
from ispa_daily_workflow.reference import SchoolReference
from ispa_daily_workflow.validation.frames import filter_by_school_ids
from ispa_daily_workflow.validation.scope import (
    ScopeSelection,
)
from ispa_daily_workflow.validation.scope import (
    parse_scope_selection as parse_scope_value_selection,
)

LOCKED_OUTPUT_IDS = (
    "sharepoint.panorama.diff.xlsx",
    "sharepoint.action_queue.xlsx",
    "sharepoint.overdue.pdf",
    "sharepoint.suspension.pdf",
)

DeliveryScope = ScopeSelection


def parse_scope_selection(
    *,
    wave: str | None,
    level: str | None,
    school: str | None,
    allowed_waves: set[str] | None = None,
    allowed_levels: set[str] | None = None,
) -> DeliveryScope:
    return parse_scope_value_selection(
        wave=wave,
        level=level,
        school=school,
        allowed_waves=allowed_waves,
        allowed_levels=allowed_levels,
    )


def resolve_compliance_history_paths_for_scope(
    *,
    compliance_history_dir: Path,
    run_date: str,
    scope: DeliveryScope,
    exact_run_date: bool = False,
) -> dict[str, Path]:
    if exact_run_date:
        available = discover_compliance_history_by_slice_for_date(
            compliance_history_dir,
            run_date=run_date,
        )
    else:
        available = discover_latest_compliance_history_by_slice(
            compliance_history_dir, run_date=run_date
        )
    if not available:
        qualifier = "for run_date=" if exact_run_date else "for or before run_date="
        raise RuntimeError(
            f"No compliance_history snapshots were found {qualifier}"
            f"{run_date} in {compliance_history_dir}"
        )

    if scope.dimension != "wave" or scope.is_all:
        return dict(sorted(available.items()))

    token = wave_to_token(scope.normalized_value)
    selected = {
        slice_token: path
        for slice_token, path in available.items()
        if slice_token == token
    }
    if not selected:
        available_tokens = ", ".join(sorted(available))
        raise RuntimeError(
            f"Scope {scope.label} did not match any compliance_history slice token. "
            f"Expected token={token!r}; available slices=[{available_tokens}]"
        )
    return dict(sorted(selected.items()))


def apply_scope_filter(
    df: pl.DataFrame,
    *,
    scope: DeliveryScope,
    reference: SchoolReference,
) -> pl.DataFrame:
    if scope.is_all:
        return df

    if scope.dimension == "school":
        return filter_by_school_ids(
            df,
            school_ids={scope.normalized_value},
            school_id_column="school_id",
        )

    if scope.dimension == "level":
        matched_ids = sorted(
            school_id
            for school_id, record in reference.by_id.items()
            if record.level == scope.normalized_value
        )
        return filter_by_school_ids(
            df,
            school_ids=matched_ids,
            school_id_column="school_id",
        )

    # `wave` scoping is enforced at slice-selection time.
    return df


def collect_scope_school_labels(
    *,
    scope: DeliveryScope,
    reference: SchoolReference,
    allowed_slice_tokens: set[str] | None = None,
) -> list[str]:
    labels: set[str] = set()
    allowed = set(allowed_slice_tokens) if allowed_slice_tokens is not None else None

    for school_id, record in sorted(reference.by_id.items()):
        if not school_id:
            continue

        if not scope.is_all:
            if scope.dimension == "school" and school_id != scope.normalized_value:
                continue
            if scope.dimension == "level" and record.level != scope.normalized_value:
                continue
            if scope.dimension == "wave" and record.wave != scope.normalized_value:
                continue

        if allowed is not None:
            if not record.wave:
                continue
            try:
                slice_token = wave_to_token(record.wave)
            except ValueError:
                continue
            if slice_token not in allowed:
                continue

        school_name = str(record.school_name).strip()
        label = f"{school_name} - {school_id}" if school_name else school_id
        if label:
            labels.add(label)

    return sorted(labels, key=str.casefold)


def total_rows_by_slice(
    frames_by_slice: dict[str, pl.DataFrame],
) -> tuple[int, dict[str, int]]:
    per_slice = {
        slice_token: frame.height
        for slice_token, frame in sorted(frames_by_slice.items())
    }
    total = sum(per_slice.values())
    return total, per_slice


def ensure_scope_non_empty(
    *,
    frames_by_slice: dict[str, pl.DataFrame],
    scope: DeliveryScope,
    label: str,
) -> None:
    total, per_slice = total_rows_by_slice(frames_by_slice)
    if total > 0:
        return
    diagnostics = (
        ", ".join(f"{slice_token}:{rows}" for slice_token, rows in per_slice.items())
        or "none"
    )
    raise RuntimeError(
        f"Scope {scope.label} resolved to zero rows for {label}. "
        f"Per-slice row counts: {diagnostics}"
    )


def materialize_scoped_outputs(
    *,
    frames_by_slice: dict[str, pl.DataFrame],
    output_dir: Path,
    filename_builder: Callable[[str], str],
    writer: Callable[[pl.DataFrame, Path], None],
    dry_run: bool,
) -> list[Path]:
    outputs: list[Path] = []
    for slice_token, frame in sorted(frames_by_slice.items()):
        path = output_dir / filename_builder(slice_token)
        outputs.append(path)
        if dry_run:
            continue
        output_dir.mkdir(parents=True, exist_ok=True)
        writer(frame, path)
    return outputs
