from __future__ import annotations

import re
from pathlib import Path

import polars as pl

from panorama_compliance.normalize.core import parse_date_value
from panorama_compliance.schema import (
    LoadedSchema,
    ValidationError,
    apply_schema_types,
    resolve_dataset_schema,
    schema_field_names,
    validate_exact_headers,
    validate_required_non_null,
)
from panorama_compliance.validation.identity import (
    ensure_additions_allowed,
    ensure_unique_identifier,
    normalize_key_column,
)
from panorama_compliance.validation.temporal import (
    parse_date_token,
    validate_temporal_bounds,
)


COMPLIANCE_HISTORY_PATTERN = re.compile(
    r"(?P<date>\d{8})_panorama_(?P<slice>.+)_compliance_history\.(?P<ext>parquet)$"
)
COMBINED_PATTERN = re.compile(
    r"(?P<date>\d{8})_panorama_(?P<slice>.+)_noncompliant\.(?P<ext>parquet)$"
)


def _read_frame(
    path: Path,
    *,
    schema: LoadedSchema | None = None,
    strict_headers: bool = True,
) -> pl.DataFrame:
    if path.suffix.lower() == ".parquet":
        frame = pl.read_parquet(path)
        if schema is None:
            return frame
        if strict_headers:
            validate_exact_headers(list(frame.columns), schema, path.name)
        typed = apply_schema_types(frame, schema)
        validate_required_non_null(typed, schema, path.name)
        return typed
    raise ValueError(
        f"Unsupported file format for compliance_history pipeline input: {path} "
        "(expected .parquet)"
    )


def _slice_from_combined(path: Path) -> str:
    match = COMBINED_PATTERN.match(path.name)
    if not match:
        raise ValueError(f"Combined file does not match naming convention: {path.name}")
    return match.group("slice")


def _find_latest_compliance_history(
    compliance_history_dir: Path,
    slice_token: str,
    run_date: str,
    *,
    include_run_date: bool = True,
) -> tuple[str, Path] | None:
    matches: list[tuple[str, Path]] = []
    for path in compliance_history_dir.glob(
        f"*_panorama_{slice_token}_compliance_history.parquet"
    ):
        match = COMPLIANCE_HISTORY_PATTERN.match(path.name)
        if not match:
            continue
        date_token = match.group("date")
        # Never seed a run from a compliance_history snapshot newer than the run date.
        if include_run_date:
            if date_token > run_date:
                continue
        elif date_token >= run_date:
            continue
        matches.append((date_token, path))
    if not matches:
        return None
    matches.sort(key=lambda item: item[0])
    return matches[-1]


def _prepare_compliance_history_rows(
    current_df: pl.DataFrame, columns: list[str]
) -> pl.DataFrame:
    frame = current_df
    for column in columns:
        if column not in frame.columns:
            frame = frame.with_columns(pl.lit(None).alias(column))
    return frame.select(columns)


def _coerce_compliant(frame: pl.DataFrame) -> pl.DataFrame:
    if "compliant" not in frame.columns:
        return frame
    return frame.with_columns(
        pl.col("compliant")
        .map_elements(parse_date_value, return_dtype=pl.Date)
        .alias("compliant")
    )


def _refresh_source_file_for_current_rows(
    *,
    history_df: pl.DataFrame,
    current_df: pl.DataFrame,
    key: str = "client_id",
    source_column: str = "source_file",
) -> pl.DataFrame:
    if (
        source_column not in history_df.columns
        or source_column not in current_df.columns
    ):
        return history_df

    latest_sources = current_df.select([key, source_column]).unique(subset=[key])
    refreshed = history_df.join(latest_sources, on=key, how="left", suffix="_current")
    current_source = f"{source_column}_current"
    if current_source not in refreshed.columns:
        return history_df

    return refreshed.with_columns(
        pl.when(pl.col(current_source).is_not_null())
        .then(pl.col(current_source))
        .otherwise(pl.col(source_column))
        .alias(source_column)
    ).drop(current_source)


def update_compliance_history(
    *,
    run_date: str,
    current_combined_path: Path,
    compliance_history_dir: Path,
    schema_root: Path,
    formats: tuple[str, ...] = ("parquet",),
    allow_additions: bool = False,
    strict_headers: bool = True,
) -> list[Path]:
    run_day = parse_date_token(run_date, field_name="run_date")
    slice_token = _slice_from_combined(current_combined_path)

    schema = resolve_dataset_schema(
        "processed.panorama.suspension_compliance_history",
        schema_root=schema_root,
    )
    noncompliant_schema = resolve_dataset_schema(
        "processed.panorama.noncompliant",
        schema_root=schema_root,
    )
    unsupported_formats = sorted({fmt.lower() for fmt in formats} - {"parquet"})
    if unsupported_formats:
        raise ValidationError(
            "Compliance History outputs are parquet-only for pipeline processing. "
            f"Unsupported format(s): {unsupported_formats}"
        )
    columns = list(schema_field_names(schema))

    current_df = _read_frame(
        current_combined_path,
        schema=noncompliant_schema,
        strict_headers=strict_headers,
    )
    current_df = normalize_key_column(
        current_df,
        key="client_id",
        label=current_combined_path.name,
    )
    ensure_unique_identifier(
        current_df, key="client_id", label=current_combined_path.name
    )
    validate_temporal_bounds(
        frame=current_df,
        run_day=run_day,
        label=current_combined_path.name,
    )

    compliance_history_dir.mkdir(parents=True, exist_ok=True)
    latest_prior = _find_latest_compliance_history(
        compliance_history_dir,
        slice_token,
        run_date,
        include_run_date=False,
    )
    latest_any = _find_latest_compliance_history(
        compliance_history_dir,
        slice_token,
        run_date,
        include_run_date=True,
    )
    latest = latest_prior or latest_any

    if latest is None:
        initialized = _prepare_compliance_history_rows(current_df, columns)
        if "compliant" in initialized.columns:
            initialized = initialized.with_columns(
                pl.lit(None, dtype=pl.Date).alias("compliant")
            )
        output_base = (
            compliance_history_dir
            / f"{run_date}_panorama_{slice_token}_compliance_history"
        )
        written: list[Path] = []
        parquet_path = output_base.with_suffix(".parquet")
        initialized.write_parquet(parquet_path)
        written.append(parquet_path)
        return written

    _, latest_path = latest
    compliance_history_df = _read_frame(
        latest_path,
        schema=schema,
        strict_headers=strict_headers,
    )
    compliance_history_df = _coerce_compliant(compliance_history_df)
    compliance_history_df = normalize_key_column(
        compliance_history_df,
        key="client_id",
        label=latest_path.name,
    )
    ensure_unique_identifier(
        compliance_history_df, key="client_id", label=latest_path.name
    )
    validate_temporal_bounds(
        frame=compliance_history_df,
        run_day=run_day,
        label=latest_path.name,
    )

    current_ids = current_df.select("client_id").unique()
    drop_off_ids = (
        compliance_history_df.filter(pl.col("compliant").is_null())
        .join(current_ids, on="client_id", how="anti")
        .select("client_id")
        .unique()
    )

    drop_ids = (
        drop_off_ids.get_column("client_id").to_list()
        if "client_id" in drop_off_ids.columns
        else []
    )
    updated = compliance_history_df.with_columns(
        pl.when(pl.col("client_id").is_in(drop_ids) & pl.col("compliant").is_null())
        .then(run_day)
        .otherwise(pl.col("compliant"))
        .alias("compliant")
    )
    updated = _refresh_source_file_for_current_rows(
        history_df=updated,
        current_df=current_df,
    )

    existing_ids = updated.select("client_id").unique()
    additions = current_df.join(existing_ids, on="client_id", how="anti")
    override_hint = (
        "If these additions are intentional, rerun with the explicit override "
        "(update-state: --allow-new-client-ids plus exactly one of --wave/--level/--school; "
        "run_daily: --allow-compliance-history-additions)."
    )
    ensure_additions_allowed(
        additions,
        key="client_id",
        allow_additions=allow_additions,
        label="Compliance History update",
        source_column="source_file",
        override_hint=override_hint,
    )
    additions = _prepare_compliance_history_rows(additions, columns)
    if "compliant" in additions.columns:
        additions = additions.with_columns(
            pl.lit(None, dtype=pl.Date).alias("compliant")
        )

    updated = _coerce_compliant(updated)
    additions = _coerce_compliant(additions)
    merged = pl.concat([updated, additions], how="vertical")
    ensure_unique_identifier(
        merged,
        key="client_id",
        label=f"updated compliance_history {slice_token}",
    )
    validate_temporal_bounds(
        frame=merged,
        run_day=run_day,
        label=f"updated compliance_history {slice_token}",
    )

    latest_comparable = _coerce_compliant(
        _prepare_compliance_history_rows(compliance_history_df, columns)
    )
    merged_comparable = merged.select(columns)
    merged_sorted = merged_comparable.sort("client_id")
    if merged_sorted.equals(
        latest_comparable.sort("client_id"),
        null_equal=True,
    ):
        if latest_any is None or latest_any[0] != run_date:
            return []

        # If a stale same-day snapshot exists, overwrite it with the deterministic
        # merged state derived from the latest prior snapshot.
        _, latest_any_path = latest_any
        if latest_any_path == latest_path:
            return []
        same_day_df = _read_frame(
            latest_any_path,
            schema=schema,
            strict_headers=strict_headers,
        )
        same_day_df = _coerce_compliant(same_day_df)
        same_day_df = normalize_key_column(
            same_day_df,
            key="client_id",
            label=latest_any_path.name,
        )
        ensure_unique_identifier(
            same_day_df, key="client_id", label=latest_any_path.name
        )
        same_day_comparable = _coerce_compliant(
            _prepare_compliance_history_rows(same_day_df, columns)
        )
        if merged_sorted.equals(same_day_comparable.sort("client_id"), null_equal=True):
            return []

    output_base = (
        compliance_history_dir / f"{run_date}_panorama_{slice_token}_compliance_history"
    )
    written: list[Path] = []
    parquet_path = output_base.with_suffix(".parquet")
    merged.write_parquet(parquet_path)
    written.append(parquet_path)

    return written
