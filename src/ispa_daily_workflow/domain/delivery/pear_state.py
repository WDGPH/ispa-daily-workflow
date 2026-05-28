from __future__ import annotations

from datetime import date
from pathlib import Path

import polars as pl

from ispa_daily_workflow.domain.delivery.routing import (
    DeliveryScope,
    apply_scope_filter,
)
from ispa_daily_workflow.domain.pear.state import (
    discover_latest_pear_authoritative_baseline_by_slice,
    discover_latest_pear_state_by_slice,
)
from ispa_daily_workflow.ingest.combine import wave_to_token
from ispa_daily_workflow.reference import (
    SchoolReference,
    resolve_school_record,
)
from ispa_daily_workflow.validation.frames import filter_by_school_ids


def resolve_pear_state_paths(
    *,
    pear_state_dir: Path,
    state_name: str,
    run_date: str,
    scope: DeliveryScope,
) -> dict[str, Path]:
    available_for_or_before = discover_latest_pear_state_by_slice(
        pear_state_dir,
        state_name=state_name,
        run_date=run_date,
    )
    available = {
        slice_token: path
        for slice_token, path in available_for_or_before.items()
        if path.name.startswith(f"{run_date}_")
    }
    if not available:
        raise RuntimeError(
            f"No PEAR {state_name} state snapshots were found for "
            f"run_date={run_date} in {pear_state_dir}"
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
            f"Scope {scope.label} did not match any PEAR state slice token. "
            f"Expected token={token!r}; available slices=[{available_tokens}]"
        )
    return dict(sorted(selected.items()))


def load_scoped_pear_state_frames(
    *,
    pear_state_dir: Path,
    state_name: str,
    run_date: str,
    scope: DeliveryScope,
    reference: SchoolReference,
) -> dict[str, pl.DataFrame]:
    state_paths = resolve_pear_state_paths(
        pear_state_dir=pear_state_dir,
        state_name=state_name,
        run_date=run_date,
        scope=scope,
    )
    frames_by_slice: dict[str, pl.DataFrame] = {}
    for slice_token, state_path in sorted(state_paths.items()):
        frame = pl.read_parquet(state_path)
        scoped_frame = apply_scope_filter(frame, scope=scope, reference=reference)
        frames_by_slice[slice_token] = scoped_frame
    return frames_by_slice


def scope_school_labels(
    *,
    scope: DeliveryScope,
    reference: SchoolReference,
    slice_tokens: set[str] | None = None,
) -> list[str]:
    from ispa_daily_workflow.domain.delivery.routing import collect_scope_school_labels

    return collect_scope_school_labels(
        scope=scope,
        reference=reference,
        allowed_slice_tokens=slice_tokens,
    )


def scope_is_after_suspension_window(
    *,
    scope: DeliveryScope,
    reference: SchoolReference,
    run_day: date,
) -> bool:
    school_labels = scope_school_labels(scope=scope, reference=reference)
    if not school_labels:
        return False
    for school_label in school_labels:
        record = resolve_school_record(reference, school_label)
        if record is None or record.suspension_window_end is None:
            return False
        if run_day <= record.suspension_window_end:
            return False
    return True


def post_window_school_labels(
    *,
    school_labels: list[str],
    reference: SchoolReference,
    run_day: date,
) -> set[str]:
    post_window: set[str] = set()
    for school_label in school_labels:
        record = resolve_school_record(reference, school_label)
        if record is None or record.suspension_window_end is None:
            continue
        if run_day > record.suspension_window_end:
            post_window.add(school_label)
    return post_window


def scope_slice_tokens_for_pear(
    *,
    scope: DeliveryScope,
    reference: SchoolReference,
) -> list[str]:
    if scope.dimension == "wave" and not scope.is_all:
        return [wave_to_token(scope.normalized_value)]

    tokens: set[str] = set()
    for school_id, record in reference.by_id.items():
        if not school_id:
            continue
        if not scope.is_all:
            if scope.dimension == "school" and school_id != scope.normalized_value:
                continue
            if scope.dimension == "level" and record.level != scope.normalized_value:
                continue
        wave_value = str(record.wave or "").strip()
        if not wave_value:
            continue
        try:
            tokens.add(wave_to_token(wave_value))
        except ValueError:
            continue
    return sorted(tokens)


def empty_pear_report_frames_for_scope(
    *,
    scope: DeliveryScope,
    reference: SchoolReference,
    report_type: str,
) -> dict[str, pl.DataFrame]:
    slice_tokens = scope_slice_tokens_for_pear(scope=scope, reference=reference)
    if not slice_tokens:
        raise RuntimeError(
            f"Scope {scope.label} resolved to zero PEAR slices for empty {report_type} fallback"
        )
    if report_type == "overdue":
        template = pl.DataFrame(
            schema={
                "client_id": pl.Utf8,
                "school_id": pl.Utf8,
                "school_name": pl.Utf8,
                "school_label": pl.Utf8,
                "first_name": pl.Utf8,
                "last_name": pl.Utf8,
                "date_of_birth": pl.Date,
            }
        )
    elif report_type == "suspension":
        template = pl.DataFrame(
            schema={
                "client_id": pl.Utf8,
                "school_id": pl.Utf8,
                "school_name": pl.Utf8,
                "school_label": pl.Utf8,
                "first_name": pl.Utf8,
                "last_name": pl.Utf8,
                "date_of_birth": pl.Date,
                "rescind_date": pl.Date,
            }
        )
    else:
        raise ValueError(f"Unsupported empty PEAR report fallback type: {report_type}")
    return {slice_token: template.clone() for slice_token in slice_tokens}


def is_empty_processed_action_queue_snapshot(
    *,
    pear_processed_dir: Path,
    run_date: str,
) -> bool:
    action_queue_paths = sorted(
        pear_processed_dir.glob(f"{run_date}_pear_suspension_vs_overdue_*.parquet")
    )
    legacy_action_queue_path = (
        pear_processed_dir / f"{run_date}_suspension_vs_overdue.parquet"
    )
    if not action_queue_paths and legacy_action_queue_path.exists():
        action_queue_paths = [legacy_action_queue_path]
    if not action_queue_paths:
        return False
    return all(pl.read_parquet(path).is_empty() for path in action_queue_paths)


def empty_action_queue_frames_for_scope(
    *,
    scope: DeliveryScope,
    reference: SchoolReference,
) -> dict[str, pl.DataFrame]:
    slice_tokens = scope_slice_tokens_for_pear(scope=scope, reference=reference)
    if not slice_tokens:
        raise RuntimeError(
            f"Scope {scope.label} resolved to zero PEAR slices for empty action queue fallback"
        )
    empty_template = pl.DataFrame(
        schema={
            "client_id": pl.Utf8,
            "school_id": pl.Utf8,
            "school_name": pl.Utf8,
            "first_name": pl.Utf8,
            "last_name": pl.Utf8,
            "date_of_birth": pl.Date,
            "action_required": pl.Utf8,
            "action_date": pl.Date,
            "level": pl.Utf8,
            "wave": pl.Utf8,
        }
    )
    return {slice_token: empty_template.clone() for slice_token in slice_tokens}


def load_scoped_pear_authoritative_baseline_frames(
    *,
    pear_processed_dir: Path,
    run_date: str,
    scope: DeliveryScope,
    reference: SchoolReference,
) -> dict[str, pl.DataFrame]:
    available_for_or_before = discover_latest_pear_authoritative_baseline_by_slice(
        pear_processed_dir,
        run_date=run_date,
        exact_run_date=True,
    )
    state_paths = {
        slice_token: path
        for slice_token, path in available_for_or_before.items()
        if path.name.startswith(f"{run_date}_")
    }
    if scope.dimension == "wave" and not scope.is_all:
        token = wave_to_token(scope.normalized_value)
        state_paths = {
            slice_token: path
            for slice_token, path in state_paths.items()
            if slice_token == token
        }
    frames_by_slice: dict[str, pl.DataFrame] = {}
    for slice_token, state_path in sorted(state_paths.items()):
        frame = pl.read_parquet(state_path)
        scoped_frame = apply_scope_filter(frame, scope=scope, reference=reference)
        frames_by_slice[slice_token] = scoped_frame
    return frames_by_slice


def apply_wave_scope_filter(
    *,
    frame: pl.DataFrame,
    scope: DeliveryScope,
    reference: SchoolReference,
) -> pl.DataFrame:
    if scope.dimension != "wave" or scope.is_all:
        return frame
    matched_ids = sorted(
        school_id
        for school_id, record in reference.by_id.items()
        if record.wave == scope.normalized_value
    )
    return filter_by_school_ids(
        frame,
        school_ids=matched_ids,
        school_id_column="school_id",
    )


def scope_waves(
    *,
    scope: DeliveryScope,
    reference: SchoolReference,
) -> set[str]:
    if scope.is_all:
        return set()
    if scope.dimension == "wave":
        return {scope.normalized_value}
    if scope.dimension == "level":
        return {
            str(record.wave).strip().upper()
            for record in reference.by_id.values()
            if str(record.level).strip().upper() == scope.normalized_value
            and str(record.wave).strip()
        }
    school_record = reference.by_id.get(scope.normalized_value)
    if school_record is None or not str(school_record.wave).strip():
        return set()
    return {str(school_record.wave).strip().upper()}
