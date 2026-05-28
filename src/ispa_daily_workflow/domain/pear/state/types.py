from __future__ import annotations

from dataclasses import dataclass

import polars as pl

from ispa_daily_workflow.domain.pear.state._common import RescindPatchSummary
from ispa_daily_workflow.domain.pear.state.selection import PearProcessedSelection


@dataclass(frozen=True)
class PearStateDerivationResult:
    selection: PearProcessedSelection
    frames: dict[str, pl.DataFrame]
    disappearance_evidence: pl.DataFrame
    disappearance_summary: dict[str, int]
    rescind_patch_summary: RescindPatchSummary
    overdue_day_over_day_summary: dict[str, object]
    prior_suspension_source: str
    critical_messages: tuple[str, ...]
    continuity_warning_messages: tuple[str, ...]
    overdue_day_over_day_warning_messages: tuple[str, ...]
    disappearance_warning_messages: tuple[str, ...]
    warning_messages: tuple[str, ...]


__all__ = ["PearStateDerivationResult"]
