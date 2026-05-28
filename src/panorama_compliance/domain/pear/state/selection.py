from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from panorama_compliance.domain.pear.state._common import (
    _ACTION_INPUT_PATTERN,
    _OVERDUE_INPUT_PATTERN,
    _SUSPENSION_INPUT_PATTERN,
    _WAVE_SLICED_PROCESSED_PATTERN,
    PROCESSED_REPORT_OVERDUE,
    PROCESSED_REPORT_SUSPENSION,
    PROCESSED_REPORT_SUSPENSION_VS_OVERDUE,
    REPORT_OVERDUE,
    REPORT_SUSPENSION,
    REPORT_SUSPENSION_VS_OVERDUE,
)


@dataclass(frozen=True)
class PearProcessedSelection:
    run_date: str
    suspension_paths: tuple[Path, ...]
    previous_suspension_paths: tuple[Path, ...]
    previous_suspension_date: str | None
    overdue_paths: tuple[Path, ...]
    suspension_vs_overdue_paths: tuple[Path, ...]
    selected_dates: dict[str, str]

    @property
    def overdue_path(self) -> Path:
        overdue_paths = self.overdue_paths
        if not overdue_paths:
            raise FileNotFoundError("No PEAR overdue processed paths were selected")
        return overdue_paths[0]

    @property
    def suspension_vs_overdue_path(self) -> Path:
        action_paths = self.suspension_vs_overdue_paths
        if not action_paths:
            raise FileNotFoundError(
                "No PEAR suspension-vs-overdue processed paths were selected"
            )
        return action_paths[0]


def _latest_date_for_run(
    *,
    available_dates: set[str],
    run_date: str,
    label: str,
) -> str:
    eligible = sorted(
        date_token for date_token in available_dates if date_token <= run_date
    )
    if not eligible:
        available = ", ".join(sorted(available_dates)) if available_dates else "none"
        raise FileNotFoundError(
            f"No {label} PEAR processed files were found for run_date={run_date}. "
            f"Available dates: {available}"
        )
    return eligible[-1]


def _latest_date_before(
    *,
    available_dates: set[str],
    before_date: str,
) -> str | None:
    eligible = sorted(
        date_token for date_token in available_dates if date_token < before_date
    )
    if not eligible:
        return None
    return eligible[-1]


def _select_overdue_paths_for_date(
    *,
    processed_dir: Path,
    date_token: str,
) -> tuple[Path, ...]:
    wave_sliced: dict[str, Path] = {}
    legacy: Path | None = None
    for path in sorted(processed_dir.glob("*.parquet")):
        name = path.name
        wave_match = _WAVE_SLICED_PROCESSED_PATTERN.match(name)
        if wave_match:
            if (
                wave_match.group("date") == date_token
                and wave_match.group("report") == PROCESSED_REPORT_OVERDUE
            ):
                wave_sliced[wave_match.group("slice")] = path
            continue
        legacy_match = _OVERDUE_INPUT_PATTERN.match(name)
        if legacy_match and legacy_match.group("date") == date_token:
            legacy = path
    if wave_sliced:
        return tuple(sorted(wave_sliced.values()))
    if legacy is not None:
        return (legacy,)
    return ()


def discover_latest_pear_processed_inputs(
    *,
    processed_dir: Path,
    run_date: str,
) -> PearProcessedSelection:
    if not processed_dir.exists():
        raise FileNotFoundError(f"PEAR processed directory not found: {processed_dir}")

    suspension_by_date_wave: dict[str, dict[str, Path]] = {}
    overdue_by_date_wave: dict[str, dict[str, Path]] = {}
    suspension_vs_overdue_by_date_wave: dict[str, dict[str, Path]] = {}
    suspension_by_date_legacy: dict[str, list[Path]] = {}
    overdue_by_date_legacy: dict[str, Path] = {}
    suspension_vs_overdue_by_date_legacy: dict[str, Path] = {}

    for path in sorted(processed_dir.glob("*.parquet")):
        name = path.name
        wave_match = _WAVE_SLICED_PROCESSED_PATTERN.match(name)
        if wave_match:
            date_token = wave_match.group("date")
            report_name = wave_match.group("report")
            slice_token = wave_match.group("slice")
            if report_name == PROCESSED_REPORT_SUSPENSION:
                suspension_by_date_wave.setdefault(date_token, {})[slice_token] = path
                continue
            if report_name == PROCESSED_REPORT_OVERDUE:
                overdue_by_date_wave.setdefault(date_token, {})[slice_token] = path
                continue
            if report_name == PROCESSED_REPORT_SUSPENSION_VS_OVERDUE:
                suspension_vs_overdue_by_date_wave.setdefault(date_token, {})[
                    slice_token
                ] = path
                continue
        match = _SUSPENSION_INPUT_PATTERN.match(name)
        if match:
            suspension_by_date_legacy.setdefault(match.group("date"), []).append(path)
            continue
        match = _OVERDUE_INPUT_PATTERN.match(name)
        if match:
            overdue_by_date_legacy[match.group("date")] = path
            continue
        match = _ACTION_INPUT_PATTERN.match(name)
        if match:
            suspension_vs_overdue_by_date_legacy[match.group("date")] = path
            continue

    suspension_date = _latest_date_for_run(
        available_dates=set(suspension_by_date_wave) | set(suspension_by_date_legacy),
        run_date=run_date,
        label="suspension",
    )
    overdue_date = _latest_date_for_run(
        available_dates=set(overdue_by_date_wave) | set(overdue_by_date_legacy),
        run_date=run_date,
        label="overdue",
    )
    suspension_vs_overdue_date = _latest_date_for_run(
        available_dates=set(suspension_vs_overdue_by_date_wave)
        | set(suspension_vs_overdue_by_date_legacy),
        run_date=run_date,
        label="suspension-vs-overdue",
    )

    suspension_paths: tuple[Path, ...]
    if suspension_date in suspension_by_date_wave:
        suspension_paths = tuple(
            sorted(suspension_by_date_wave[suspension_date].values())
        )
    else:
        suspension_paths = tuple(sorted(suspension_by_date_legacy[suspension_date]))
    if not suspension_paths:
        raise FileNotFoundError(
            "No suspension PEAR processed files were selected for "
            f"run_date={run_date} (date={suspension_date})"
        )
    previous_suspension_date = _latest_date_before(
        available_dates=set(suspension_by_date_wave) | set(suspension_by_date_legacy),
        before_date=suspension_date,
    )
    previous_suspension_paths: tuple[Path, ...] = ()
    if previous_suspension_date is not None:
        if previous_suspension_date in suspension_by_date_wave:
            previous_suspension_paths = tuple(
                sorted(suspension_by_date_wave[previous_suspension_date].values())
            )
        else:
            previous_suspension_paths = tuple(
                sorted(suspension_by_date_legacy[previous_suspension_date])
            )

    overdue_paths: tuple[Path, ...]
    if overdue_date in overdue_by_date_wave:
        overdue_paths = tuple(sorted(overdue_by_date_wave[overdue_date].values()))
    else:
        overdue_paths = (overdue_by_date_legacy[overdue_date],)

    suspension_vs_overdue_paths: tuple[Path, ...]
    if suspension_vs_overdue_date in suspension_vs_overdue_by_date_wave:
        suspension_vs_overdue_paths = tuple(
            sorted(
                suspension_vs_overdue_by_date_wave[suspension_vs_overdue_date].values()
            )
        )
    else:
        suspension_vs_overdue_paths = (
            suspension_vs_overdue_by_date_legacy[suspension_vs_overdue_date],
        )

    return PearProcessedSelection(
        run_date=run_date,
        suspension_paths=suspension_paths,
        previous_suspension_paths=previous_suspension_paths,
        previous_suspension_date=previous_suspension_date,
        overdue_paths=overdue_paths,
        suspension_vs_overdue_paths=suspension_vs_overdue_paths,
        selected_dates={
            REPORT_SUSPENSION: suspension_date,
            REPORT_OVERDUE: overdue_date,
            REPORT_SUSPENSION_VS_OVERDUE: suspension_vs_overdue_date,
        },
    )


__all__ = [
    "PearProcessedSelection",
    "discover_latest_pear_processed_inputs",
]
