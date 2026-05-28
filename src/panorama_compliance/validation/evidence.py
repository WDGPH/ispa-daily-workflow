from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Iterable

import polars as pl

from panorama_compliance.normalize.core import parse_date_value
from panorama_compliance.validation.catalog import RULE_PARSE_COUNTERS_ID
from panorama_compliance.validation.models import RuleResult


@dataclass(frozen=True)
class ParseFailureCounter:
    stream: str
    field: str
    failed_count: int
    non_empty_count: int

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


def _as_trimmed_string_expr(column: str) -> pl.Expr:
    return (
        pl.col(column)
        .cast(pl.Utf8, strict=False)
        .fill_null("")
        .str.strip_chars()
        .alias(column)
    )


def collect_date_parse_counters(
    frame: pl.DataFrame,
    *,
    stream: str,
    fields: Iterable[str],
) -> list[ParseFailureCounter]:
    counters: list[ParseFailureCounter] = []
    for field in fields:
        if field not in frame.columns:
            continue
        raw = frame.with_columns(_as_trimmed_string_expr(field))
        with_flags = raw.with_columns(
            pl.col(field)
            .map_elements(parse_date_value, return_dtype=pl.Date)
            .alias("_p"),
            (pl.col(field) != "").alias("_non_empty"),
        )
        failed = with_flags.filter(pl.col("_non_empty") & pl.col("_p").is_null()).height
        non_empty = with_flags.filter(pl.col("_non_empty")).height
        counters.append(
            ParseFailureCounter(
                stream=stream,
                field=field,
                failed_count=int(failed),
                non_empty_count=int(non_empty),
            )
        )
    return counters


def aggregate_parse_counters(
    counters: Iterable[ParseFailureCounter],
) -> dict[str, dict[str, int]]:
    totals: dict[str, dict[str, int]] = {}
    for counter in counters:
        field_totals = totals.setdefault(
            counter.field,
            {"failed_count": 0, "non_empty_count": 0},
        )
        field_totals["failed_count"] += counter.failed_count
        field_totals["non_empty_count"] += counter.non_empty_count
    return totals


def parse_counter_alerts(
    counters: Iterable[ParseFailureCounter],
    *,
    rule_id: str = RULE_PARSE_COUNTERS_ID,
) -> list[RuleResult]:
    results: list[RuleResult] = []
    for counter in counters:
        if counter.failed_count <= 0:
            continue
        message = (
            f"Date parse failures detected for {counter.field} in {counter.stream}: "
            f"{counter.failed_count}/{counter.non_empty_count} non-empty rows"
        )
        results.append(
            RuleResult(
                rule_id=rule_id,
                code="date_parse_failure_count",
                severity="warning",
                message=message,
                count=counter.failed_count,
                context=counter.as_dict(),
            )
        )
    return results
