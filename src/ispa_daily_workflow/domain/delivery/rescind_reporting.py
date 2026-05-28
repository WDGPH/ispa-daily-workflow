from __future__ import annotations

from datetime import date

import polars as pl


def _normalize_current_frame(current_frame: pl.DataFrame) -> pl.DataFrame:
    return current_frame.with_columns(
        pl.col("compliant").cast(pl.Date, strict=False).alias("compliant")
    )


def _normalize_previous_frame(
    previous_authoritative_frame: pl.DataFrame,
) -> pl.DataFrame:
    return previous_authoritative_frame.with_columns(
        pl.col("rescind_date").cast(pl.Date, strict=False).alias("rescind_date")
    )


def _current_rescinds_in_window(
    *,
    current: pl.DataFrame,
    run_day: date,
    prev_business_day: date,
) -> pl.DataFrame:
    return (
        current.filter(
            pl.col("compliant").is_not_null()
            & (pl.col("compliant") >= pl.lit(prev_business_day))
            & (pl.col("compliant") <= pl.lit(run_day))
        )
        .select("client_id", "compliant")
        .unique()
    )


def _prior_active_ids(
    *,
    previous: pl.DataFrame,
    prev_business_day: date,
) -> pl.DataFrame:
    return (
        previous.filter(
            pl.col("rescind_date").is_null()
            | (pl.col("rescind_date") > pl.lit(prev_business_day))
        )
        .select("client_id")
        .unique()
    )


def rescind_reporting_diagnostics(
    *,
    current_frame: pl.DataFrame,
    previous_authoritative_frame: pl.DataFrame,
    run_day: date,
    prev_business_day: date,
) -> dict[str, int]:
    current = _normalize_current_frame(current_frame)
    previous = _normalize_previous_frame(previous_authoritative_frame)
    current_rescinds = _current_rescinds_in_window(
        current=current,
        run_day=run_day,
        prev_business_day=prev_business_day,
    )
    prior_active = _prior_active_ids(
        previous=previous,
        prev_business_day=prev_business_day,
    )
    transitions = current_rescinds.join(prior_active, on="client_id", how="inner")
    prior_rescinded = (
        previous.filter(pl.col("rescind_date").is_not_null())
        .select("client_id", "rescind_date")
        .unique()
    )
    date_shift_only = (
        current_rescinds.join(prior_rescinded, on="client_id", how="inner")
        .filter(pl.col("rescind_date") != pl.col("compliant"))
        .join(
            transitions.select("client_id").unique(),
            on="client_id",
            how="anti",
        )
        .select("client_id")
        .unique()
    )
    current_active = (
        current.filter(
            pl.col("compliant").is_null() | (pl.col("compliant") > pl.lit(run_day))
        )
        .select("client_id")
        .unique()
    )
    return {
        "rescinds_transition_count": int(transitions.height),
        "rescinds_date_shift_only_count": int(date_shift_only.height),
        "prior_active_count": int(prior_active.height),
        "current_active_count": int(current_active.height),
    }


def mark_unreported_rescinds_for_suspension_report(
    *,
    current_frame: pl.DataFrame,
    previous_authoritative_frame: pl.DataFrame,
    run_day: date,
    prev_business_day: date,
) -> tuple[pl.DataFrame, int]:
    current = _normalize_current_frame(current_frame)
    previous = _normalize_previous_frame(previous_authoritative_frame)
    current_rescinds = _current_rescinds_in_window(
        current=current,
        run_day=run_day,
        prev_business_day=prev_business_day,
    )
    prior_active = _prior_active_ids(
        previous=previous,
        prev_business_day=prev_business_day,
    )
    unreported = current_rescinds.join(
        prior_active, on="client_id", how="inner"
    ).with_columns(pl.lit(True).alias("_report_rescinded"))
    marked = (
        current.join(
            unreported,
            on=["client_id", "compliant"],
            how="left",
        )
        .with_columns(
            pl.col("_report_rescinded").fill_null(False).alias("report_rescinded")
        )
        .drop("_report_rescinded")
    )
    return marked, int(unreported.height)
