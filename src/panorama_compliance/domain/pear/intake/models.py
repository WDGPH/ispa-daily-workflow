from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

import polars as pl

from panorama_compliance.reference import WaveWindow


@dataclass(frozen=True)
class FooterMetadata:
    report_date: date
    report_time: str
    page_token: str | None
    reported_total_count: int | None


@dataclass(frozen=True)
class LandingReport:
    path: Path
    report_type: str
    title_text: str
    footer: FooterMetadata
    data_start_row: int
    data_end_row: int
    landing_frame: pl.DataFrame
    source_rows: list[dict[str, Any]]
    canonical_filename: str
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class ProcessedReport:
    landing: LandingReport
    processed_frame: pl.DataFrame
    canonical_filename: str
    report_warnings: tuple[str, ...] = ()
    no_action_count: int = 0


@dataclass
class RunOutcome:
    source_file: Path
    report_type: str | None = None
    status: str = "FAIL"
    error: str | None = None
    warnings: list[str] = field(default_factory=list)
    landing_rows: int = 0
    processed_rows: int = 0
    no_action_rows: int = 0
    report_date: str | None = None
    canonical_filename: str | None = None


__all__ = [
    "WaveWindow",
    "FooterMetadata",
    "LandingReport",
    "ProcessedReport",
    "RunOutcome",
]
