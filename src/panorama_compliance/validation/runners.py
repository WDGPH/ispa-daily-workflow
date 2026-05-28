from __future__ import annotations

from datetime import date

import polars as pl

from panorama_compliance.validation.models import RuleResult
from panorama_compliance.validation.temporal import validate_temporal_bounds


def run_update_state_validations(
    *,
    stage: str,
    frame: pl.DataFrame | None = None,
    run_day: date | None = None,
    label: str = "",
) -> list[RuleResult]:
    if stage != "U-E" or frame is None or run_day is None:
        return []
    return validate_temporal_bounds(frame=frame, run_day=run_day, label=label)


def run_delivery_validations(
    *,
    stage: str,
    frame: pl.DataFrame | None = None,
    run_day: date | None = None,
    label: str = "",
) -> list[RuleResult]:
    if stage != "D-D" or frame is None or run_day is None:
        return []
    return validate_temporal_bounds(frame=frame, run_day=run_day, label=label)
