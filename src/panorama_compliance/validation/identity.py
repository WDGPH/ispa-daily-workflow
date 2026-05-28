from __future__ import annotations

import polars as pl

from panorama_compliance.schema import ValidationError, validate_unique_key


def sample_key_values(
    frame: pl.DataFrame,
    *,
    key: str,
    limit: int = 20,
) -> list[str]:
    if key not in frame.columns:
        return []
    return [
        str(value) for value in frame.get_column(key).drop_nulls().head(limit).to_list()
    ]


def all_key_values(frame: pl.DataFrame, *, key: str) -> list[str]:
    if key not in frame.columns:
        return []
    values = frame.get_column(key).drop_nulls().to_list()
    normalized = {str(value) for value in values if str(value).strip()}
    return sorted(normalized)


def key_source_rows(
    frame: pl.DataFrame,
    *,
    key: str,
    source_column: str,
) -> list[dict[str, str | None]]:
    if key not in frame.columns or source_column not in frame.columns:
        return []

    pairs = frame.select([key, source_column]).unique().sort(key).to_dicts()
    rows: list[dict[str, str | None]] = []
    for pair in pairs:
        key_value = pair.get(key)
        if key_value is None:
            continue
        source_value = pair.get(source_column)
        rows.append(
            {
                key: str(key_value),
                source_column: None if source_value is None else str(source_value),
            }
        )
    return rows


def ensure_key_column(frame: pl.DataFrame, *, key: str, label: str) -> None:
    if key not in frame.columns:
        raise ValidationError(f"{label}: missing {key}")


def normalize_key_column(
    frame: pl.DataFrame,
    *,
    key: str,
    label: str,
    empty_to_null: bool = False,
) -> pl.DataFrame:
    ensure_key_column(frame, key=key, label=label)
    expr = pl.col(key).cast(pl.Utf8).str.strip_chars().str.replace(r"\.0$", "")
    if empty_to_null:
        expr = pl.when(expr == "").then(None).otherwise(expr)
    return frame.with_columns(expr.alias(key))


def ensure_unique_identifier(frame: pl.DataFrame, *, key: str, label: str) -> None:
    ensure_key_column(frame, key=key, label=label)
    validate_unique_key(frame, key, label)


def subset_difference(
    subset_df: pl.DataFrame,
    superset_df: pl.DataFrame,
    *,
    key: str,
    subset_label: str,
    superset_label: str,
) -> pl.DataFrame:
    ensure_key_column(subset_df, key=key, label=subset_label)
    ensure_key_column(superset_df, key=key, label=superset_label)
    return (
        subset_df.select(key)
        .unique()
        .join(superset_df.select(key).unique(), on=key, how="anti")
    )


def ensure_subset(
    subset_df: pl.DataFrame,
    superset_df: pl.DataFrame,
    *,
    key: str,
    subset_label: str,
    superset_label: str,
    error_prefix: str,
) -> None:
    outside = subset_difference(
        subset_df,
        superset_df,
        key=key,
        subset_label=subset_label,
        superset_label=superset_label,
    )
    if outside.is_empty():
        return
    sample_values = sample_key_values(outside, key=key)
    raise ValidationError(
        f"{error_prefix}: {subset_label} contains {outside.height} {key} values not in {superset_label}. "
        f"sample_{key}={sample_values}"
    )


def ensure_additions_allowed(
    additions: pl.DataFrame,
    *,
    key: str,
    allow_additions: bool,
    label: str,
    source_column: str | None = None,
    override_hint: str | None = None,
) -> None:
    if additions.is_empty() or allow_additions:
        return
    affected_ids = all_key_values(additions, key=key)
    message_parts = [
        f"{label} detected unexpected {key} additions ({additions.height} rows).",
        f"affected_{key}s={affected_ids}",
    ]

    if source_column is not None and source_column in additions.columns:
        affected_sources = all_key_values(additions, key=source_column)
        source_rows = key_source_rows(additions, key=key, source_column=source_column)
        message_parts.append(f"{source_column}s={affected_sources}")
        message_parts.append(f"{key}_to_{source_column}={source_rows}")

    if override_hint:
        message_parts.append(override_hint.strip())

    raise ValidationError(" ".join(message_parts))
