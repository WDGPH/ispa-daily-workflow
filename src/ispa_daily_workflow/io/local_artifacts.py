from __future__ import annotations

import shutil
from datetime import date
from pathlib import Path

from ispa_daily_workflow.io.workdays import parse_run_date

INSPECT_RETENTION_DAYS = 14
STATE_SYNC_RETENTION_DAYS = 7
DATA_QUALITY_RETENTION_DAYS = 30


def clear_matching_files(directory: Path, *, pattern: str) -> int:
    if not directory.exists():
        return 0
    removed = 0
    for path in directory.glob(pattern):
        if path.is_file():
            path.unlink()
            removed += 1
    return removed


def clear_directory(directory: Path, *, ignore_errors: bool = False) -> None:
    shutil.rmtree(directory, ignore_errors=ignore_errors)


def _parse_run_date_token(value: str) -> date | None:
    token = value[:8]
    if len(token) != 8 or not token.isdigit():
        return None
    try:
        return parse_run_date(token)
    except ValueError:
        return None


def _prune_run_dated_directories(
    *,
    root: Path,
    keep_days: int,
    today: date,
) -> int:
    if keep_days < 0 or not root.exists():
        return 0
    removed = 0
    for child in root.iterdir():
        if not child.is_dir():
            continue
        run_day = _parse_run_date_token(child.name)
        if run_day is None:
            continue
        age_days = (today - run_day).days
        if age_days > keep_days:
            clear_directory(child, ignore_errors=True)
            removed += 1
    return removed


def _prune_run_dated_files(
    *,
    root: Path,
    keep_days: int,
    today: date,
) -> int:
    if keep_days < 0 or not root.exists():
        return 0
    removed = 0
    for path in root.iterdir():
        if not path.is_file():
            continue
        run_day = _parse_run_date_token(path.name)
        if run_day is None:
            continue
        age_days = (today - run_day).days
        if age_days > keep_days:
            path.unlink(missing_ok=True)
            removed += 1
    return removed


def run_retention_cleanup(
    *,
    output_root: Path,
    artifacts_root: Path,
    input_root: Path | None,
    today: date,
) -> dict[str, int]:
    inspect_removed = _prune_run_dated_directories(
        root=output_root / "inspect",
        keep_days=INSPECT_RETENTION_DAYS,
        today=today,
    )
    state_sync_removed = 0
    if input_root is not None:
        state_sync_removed = _prune_run_dated_directories(
            root=input_root / "state_sync",
            keep_days=STATE_SYNC_RETENTION_DAYS,
            today=today,
        )
    data_quality_removed = _prune_run_dated_files(
        root=artifacts_root / "data_quality",
        keep_days=DATA_QUALITY_RETENTION_DAYS,
        today=today,
    )
    return {
        "inspect_run_dirs_removed": inspect_removed,
        "state_sync_run_dirs_removed": state_sync_removed,
        "data_quality_files_removed": data_quality_removed,
    }
