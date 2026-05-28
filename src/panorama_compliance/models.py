from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any


@dataclass
class FileManifest:
    path: Path
    original_suffix: str
    detected_suffix: str | None
    detected_format: str | None
    renamed_to: Path | None
    size_bytes: int
    modified_time: datetime
    created_time: datetime | None
    header: list[str] | None = None
    schema_errors: list[str] = field(default_factory=list)
    schema_warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ReportPaths:
    output_dir: Path
    typst_path: Path
    pdf_path: Path


@dataclass
class ReportOutput:
    report_type: str
    school_label: str
    pdf_path: Path
    counts: dict[str, int]
    id_stats: dict[str, int]
    terminal_status: str | None = None


@dataclass
class PipelineConfig:
    run_date: date
    previous_business_day: date | None
    input_root: Path
    input_raw: Path
    input_renamed: Path
    output_root: Path
    artifacts_root: Path
    logs_root: Path
    reference_path: Path
    schema_root: Path
    logo_path: Path
    typst_bin: str
    no_compile: bool
    prune_history: bool
    keep_artifacts: bool
    redact_long_numeric_ids: bool = False


@dataclass
class DiffResult:
    current_date: str
    previous_date: str
    slice_token: str
    became_compliant_rows: int
    current_only_rows: int
    output_path: Path


@dataclass
class AlertRecord:
    code: str
    level: str
    message: str
    context: dict[str, Any] = field(default_factory=dict)
