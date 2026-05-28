from __future__ import annotations

import json
from pathlib import Path

import polars as pl

from panorama_compliance.models import AlertRecord


def build_alerts(
    *,
    current_df: pl.DataFrame,
    previous_df: pl.DataFrame | None,
    expected_input_count: int | None,
    observed_input_count: int,
    missing_input_threshold: int = 0,
    percent_change_threshold: float = 0.25,
) -> list[AlertRecord]:
    alerts: list[AlertRecord] = []

    if expected_input_count is not None:
        missing = max(0, expected_input_count - observed_input_count)
        if missing > missing_input_threshold:
            alerts.append(
                AlertRecord(
                    code="missing_inputs",
                    level="warning",
                    message=(
                        f"Observed {observed_input_count} input files but expected {expected_input_count}"
                    ),
                    context={
                        "expected_input_count": expected_input_count,
                        "observed_input_count": observed_input_count,
                        "missing_input_count": missing,
                    },
                )
            )

    if (
        previous_df is not None
        and not previous_df.is_empty()
        and "school_label" in current_df.columns
        and "school_label" in previous_df.columns
    ):
        current_counts = (
            current_df.group_by("school_label").len().rename({"len": "current_rows"})
        )
        previous_counts = (
            previous_df.group_by("school_label").len().rename({"len": "previous_rows"})
        )
        merged = current_counts.join(previous_counts, on="school_label", how="full")
        if "school_label_right" in merged.columns:
            merged = merged.with_columns(
                pl.coalesce(
                    [pl.col("school_label"), pl.col("school_label_right")]
                ).alias("school_label")
            ).drop("school_label_right")
        merged = merged.with_columns(
            pl.col("school_label").fill_null("UNKNOWN"),
            pl.col("current_rows").fill_null(0).cast(pl.Int64),
            pl.col("previous_rows").fill_null(0).cast(pl.Int64),
        ).with_columns(
            pl.when(pl.col("previous_rows") == 0)
            .then(None)
            .otherwise(
                (pl.col("current_rows") - pl.col("previous_rows"))
                / pl.col("previous_rows")
            )
            .alias("pct_change"),
            (pl.col("current_rows") - pl.col("previous_rows")).alias("row_delta"),
        )

        anomalies = (
            merged.filter(pl.col("pct_change").abs() > percent_change_threshold)
            .sort("pct_change", descending=True)
            .to_dicts()
        )
        for item in anomalies:
            alerts.append(
                AlertRecord(
                    code="school_row_delta",
                    level="warning",
                    message=(
                        f"School {item['school_label']} changed by {item['pct_change']:.2%} "
                        f"({item['previous_rows']} -> {item['current_rows']})"
                    ),
                    context={
                        "school_label": item["school_label"],
                        "previous_rows": int(item["previous_rows"]),
                        "current_rows": int(item["current_rows"]),
                        "row_delta": int(item["row_delta"]),
                        "pct_change": float(item["pct_change"]),
                    },
                )
            )

    return alerts


def write_alerts(path: Path, alerts: list[AlertRecord]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = [
        {
            "code": alert.code,
            "level": alert.level,
            "message": alert.message,
            "context": alert.context,
        }
        for alert in alerts
    ]
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path
