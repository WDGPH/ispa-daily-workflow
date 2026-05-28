from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

from panorama_compliance.domain.pear.state._common import (
    _format_date_token,
    _parse_date_token,
    _SUSPENSION_INPUT_PATTERN,
    _WAVE_SLICED_PROCESSED_PATTERN,
    PROCESSED_REPORT_SUSPENSION,
)
from panorama_compliance.domain.pear.state.selection import PearProcessedSelection
from panorama_compliance.ingest.combine import wave_to_token
from panorama_compliance.domain.common.workdays import WorkdayInfo
from panorama_compliance.reference import SchoolReference, WaveWindow
from panorama_compliance.schema import ValidationError
from panorama_compliance.validation.catalog import (
    RULE_PEAR_SUSPENSION_CONTINUITY_ID,
    RULE_PEAR_WAVE_WINDOW_AUTHORITY_ID,
)
from panorama_compliance.validation.pear import require_wave_window_authority


@dataclass(frozen=True)
class SuspensionContinuityPlan:
    prior_suspension_paths: tuple[Path, ...]
    previous_suspension_date: str | None
    comparison_waves: tuple[str, ...]
    warning_messages: tuple[str, ...]


def _suffix_for_level(level: str) -> str:
    normalized = str(level).strip().upper()
    if normalized == "ELEMENTARY":
        return "elementary"
    if normalized == "SECONDARY":
        return "secondary"
    raise ValidationError(
        f"Unsupported school level for suspension continuity checks: {level!r}"
    )


def _wave_level_map(reference: SchoolReference) -> dict[str, str]:
    wave_levels: dict[str, str] = {}
    for record in reference.by_id.values():
        wave = str(record.wave or "").strip().upper()
        level = str(record.level or "").strip().upper()
        if not wave or not level:
            continue
        existing = wave_levels.get(wave)
        if existing is not None and existing != level:
            raise ValidationError(
                "School reference has conflicting levels for wave "
                f"{wave}: {existing} vs {level}"
            )
        wave_levels[wave] = level
    return wave_levels


def _resolve_wave_windows(reference: SchoolReference) -> dict[str, WaveWindow]:
    return require_wave_window_authority(
        reference=reference,
        context="PEAR suspension continuity checks",
        rule_id=RULE_PEAR_WAVE_WINDOW_AUTHORITY_ID,
    )


@dataclass(frozen=True)
class _SuspensionCoverageIndex:
    waves_by_date: dict[str, set[str]]
    paths_by_date: dict[str, tuple[Path, ...]]


def _build_suspension_coverage_index(
    *,
    processed_dir: Path,
    reference: SchoolReference,
) -> _SuspensionCoverageIndex:
    wave_levels = _wave_level_map(reference)
    level_to_waves: dict[str, set[str]] = {"ELEMENTARY": set(), "SECONDARY": set()}
    token_to_wave: dict[str, str] = {}
    for wave, level in sorted(wave_levels.items()):
        if level in level_to_waves:
            level_to_waves[level].add(wave)
        token_to_wave[wave_to_token(wave)] = wave

    waves_by_date: dict[str, set[str]] = {}
    paths_by_date: dict[str, set[Path]] = {}

    for path in sorted(processed_dir.glob("*.parquet")):
        name = path.name
        wave_match = _WAVE_SLICED_PROCESSED_PATTERN.match(name)
        if wave_match and wave_match.group("report") == PROCESSED_REPORT_SUSPENSION:
            date_token = wave_match.group("date")
            slice_token = wave_match.group("slice")
            resolved_wave = token_to_wave.get(slice_token)
            if resolved_wave is not None:
                waves_by_date.setdefault(date_token, set()).add(resolved_wave)
            paths_by_date.setdefault(date_token, set()).add(path)
            continue

        legacy_match = _SUSPENSION_INPUT_PATTERN.match(name)
        if legacy_match is None:
            continue
        date_token = legacy_match.group("date")
        suffix = legacy_match.group("suffix").lower()
        level = "ELEMENTARY" if suffix == "elementary" else "SECONDARY"
        waves_by_date.setdefault(date_token, set()).update(level_to_waves[level])
        paths_by_date.setdefault(date_token, set()).add(path)

    return _SuspensionCoverageIndex(
        waves_by_date=waves_by_date,
        paths_by_date={
            date_token: tuple(sorted(paths))
            for date_token, paths in sorted(paths_by_date.items())
        },
    )


def _initial_suspension_business_day(
    *,
    wave: str,
    window: WaveWindow,
    workdays: dict[date, WorkdayInfo],
) -> date:
    start_info = workdays.get(window.suspension_window_start)
    if start_info is None:
        raise ValidationError(
            f"VALIDATION FAIL [{RULE_PEAR_SUSPENSION_CONTINUITY_ID}] "
            "run.workdays_csv is missing suspension_window_start "
            f"{window.suspension_window_start.isoformat()} for wave={wave}"
        )
    if start_info.previous_business_day is None:
        raise ValidationError(
            f"VALIDATION FAIL [{RULE_PEAR_SUSPENSION_CONTINUITY_ID}] "
            "run.workdays_csv is missing Previous Business Day for "
            f"suspension_window_start={window.suspension_window_start.isoformat()} "
            f"wave={wave}"
        )
    return start_info.previous_business_day


def _build_suspension_continuity_plan(
    *,
    selection: PearProcessedSelection,
    reference: SchoolReference,
    workdays: dict[date, WorkdayInfo],
    continuity_waived_waves: set[str] | None = None,
) -> SuspensionContinuityPlan:
    run_day = _parse_date_token(selection.run_date, label="run_date")
    run_info = workdays.get(run_day)
    if run_info is None:
        raise ValidationError(
            f"VALIDATION FAIL [{RULE_PEAR_SUSPENSION_CONTINUITY_ID}] "
            "run.workdays_csv is missing run_date "
            f"{run_day.isoformat()} required for suspension continuity checks"
        )
    if not run_info.business_day:
        return SuspensionContinuityPlan(
            prior_suspension_paths=(),
            previous_suspension_date=None,
            comparison_waves=(),
            warning_messages=(
                f"run_date={selection.run_date} is not a business day; "
                "skipping suspension continuity checks",
            ),
        )

    if not selection.suspension_paths:
        return SuspensionContinuityPlan(
            prior_suspension_paths=(),
            previous_suspension_date=None,
            comparison_waves=(),
            warning_messages=(),
        )

    processed_dir = selection.suspension_paths[0].parent
    suspension_coverage = _build_suspension_coverage_index(
        processed_dir=processed_dir,
        reference=reference,
    )
    wave_levels = _wave_level_map(reference)
    wave_windows = _resolve_wave_windows(reference)

    warnings: list[str] = []
    comparison_waves: set[str] = set()
    previous_suspension_date: str | None = None
    previous_business_day = run_info.previous_business_day
    waived_waves = {
        str(value).strip().upper()
        for value in (continuity_waived_waves or set())
        if str(value).strip()
    }

    for wave, window in sorted(wave_windows.items()):
        level = wave_levels.get(wave)
        if level is None:
            continue
        initial_day = _initial_suspension_business_day(
            wave=wave,
            window=window,
            workdays=workdays,
        )
        initial_token = _format_date_token(initial_day)
        run_token = selection.run_date

        if run_day < window.applied_date or run_day > window.suspension_window_end:
            continue

        initial_coverage = suspension_coverage.waves_by_date.get(initial_token, set())
        if run_day < window.suspension_window_start and wave not in initial_coverage:
            warnings.append(
                f"run_date={run_token} wave={wave} level={level}: "
                "initial suspension list not yet provided; "
                "expected by previous business day before "
                f"suspension_window_start ({initial_token}); "
                "suspension_window_start="
                f"{_format_date_token(window.suspension_window_start)}"
            )

        if initial_day <= run_day <= window.suspension_window_end:
            current_coverage = suspension_coverage.waves_by_date.get(run_token, set())
            if wave not in current_coverage:
                suffix = _suffix_for_level(level)
                raise ValidationError(
                    f"VALIDATION FAIL [{RULE_PEAR_SUSPENSION_CONTINUITY_ID}] "
                    "Suspension continuity check failed for "
                    f"wave={wave} level={level}: missing current suspension list "
                    f"{run_token}_suspension_list_{suffix}.parquet "
                    "(or wave-sliced equivalent)"
                )

            if run_day > initial_day:
                if previous_business_day is None:
                    if wave in waived_waves:
                        warnings.append(
                            f"run_date={run_token} wave={wave} level={level}: "
                            "continuity bootstrap bypass enabled; previous business "
                            "day is unavailable in run.workdays.csv; skipping prior "
                            "suspension comparison for this wave"
                        )
                        continue
                    raise ValidationError(
                        f"VALIDATION FAIL [{RULE_PEAR_SUSPENSION_CONTINUITY_ID}] "
                        "run.workdays_csv is missing Previous Business Day for run_date "
                        f"{run_token}; required for suspension continuity checks"
                    )
                previous_token = _format_date_token(previous_business_day)
                previous_suspension_date = previous_token
                previous_coverage = suspension_coverage.waves_by_date.get(
                    previous_token,
                    set(),
                )
                if wave not in previous_coverage:
                    suffix = _suffix_for_level(level)
                    if wave in waived_waves:
                        warnings.append(
                            f"run_date={run_token} wave={wave} level={level}: "
                            "continuity bootstrap bypass enabled; missing previous "
                            "business day suspension list "
                            f"{previous_token}_suspension_list_{suffix}.parquet "
                            "(or wave-sliced equivalent); "
                            "skipping prior suspension comparison for this wave"
                        )
                        continue
                    raise ValidationError(
                        f"VALIDATION FAIL [{RULE_PEAR_SUSPENSION_CONTINUITY_ID}] "
                        "Suspension continuity check failed for "
                        f"wave={wave} level={level}: missing previous business day "
                        f"suspension list {previous_token}_suspension_list_{suffix}.parquet "
                        "(or wave-sliced equivalent)"
                    )
                comparison_waves.add(wave)

    prior_paths: tuple[Path, ...] = ()
    if previous_suspension_date is not None and comparison_waves:
        prior_paths = suspension_coverage.paths_by_date.get(
            previous_suspension_date, ()
        )
    return SuspensionContinuityPlan(
        prior_suspension_paths=prior_paths,
        previous_suspension_date=previous_suspension_date,
        comparison_waves=tuple(sorted(comparison_waves)),
        warning_messages=tuple(warnings),
    )


__all__ = ["SuspensionContinuityPlan"]
