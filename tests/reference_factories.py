from __future__ import annotations

from datetime import date

from panorama_compliance.domain.common.workdays import WorkdayInfo
from panorama_compliance.reference import SchoolRecord, SchoolReference, WaveWindow


def school_record(
    *,
    school_name: str,
    school_id: str,
    level: str = "ELEMENTARY",
    wave: str = "ELEMENTARY1",
    fq_group: str = "GROUP1",
) -> SchoolRecord:
    return SchoolRecord(
        school_name=school_name,
        school_id=school_id,
        level=level,
        wave=wave,
        fq_group=fq_group,
    )


def elementary_wave_window() -> WaveWindow:
    return WaveWindow(
        applied_date=date(2026, 2, 9),
        suspension_window_start=date(2026, 2, 25),
        suspension_window_end=date(2026, 3, 24),
    )


def secondary_wave_window() -> WaveWindow:
    return WaveWindow(
        applied_date=date(2026, 1, 28),
        suspension_window_start=date(2026, 2, 11),
        suspension_window_end=date(2026, 3, 10),
    )


def reference_from_records(
    records: list[SchoolRecord],
    *,
    secondary_labels: set[str] | None = None,
    with_wave_windows: bool = True,
) -> SchoolReference:
    wave_windows = (
        {
            "ELEMENTARY1": elementary_wave_window(),
            "SECONDARY1": secondary_wave_window(),
        }
        if with_wave_windows
        else {}
    )
    return SchoolReference(
        by_id={
            record.school_id: record
            for record in records
            if record.school_id is not None
        },
        by_name={record.school_name: record for record in records},
        secondary_labels=secondary_labels or set(),
        wave_windows=wave_windows,
    )


def alpha_beta_reference(
    *,
    secondary_labels: set[str] | None = None,
    with_wave_windows: bool = True,
) -> SchoolReference:
    return reference_from_records(
        [
            school_record(
                school_name="ALPHA ELEMENTARY SCHOOL",
                school_id="1001",
                level="ELEMENTARY",
                wave="ELEMENTARY1",
                fq_group="GROUP1",
            ),
            school_record(
                school_name="BETA SECONDARY SCHOOL",
                school_id="3001",
                level="SECONDARY",
                wave="SECONDARY1",
                fq_group="GROUPA",
            ),
        ],
        secondary_labels=secondary_labels,
        with_wave_windows=with_wave_windows,
    )


def alpha_school_reference(
    *,
    school_name: str = "ALPHA ELEMENTARY SCHOOL",
    with_wave_windows: bool = True,
) -> SchoolReference:
    return reference_from_records(
        [
            school_record(
                school_name=school_name,
                school_id="1001",
                level="ELEMENTARY",
                wave="ELEMENTARY1",
                fq_group="GROUP1",
            )
        ],
        with_wave_windows=with_wave_windows,
    )


def business_workdays() -> dict[date, WorkdayInfo]:
    return {
        date(2026, 2, 20): WorkdayInfo(
            holiday="",
            business_day=True,
            previous_business_day=date(2026, 2, 19),
        ),
        date(2026, 2, 24): WorkdayInfo(
            holiday="",
            business_day=True,
            previous_business_day=date(2026, 2, 23),
        ),
        date(2026, 2, 25): WorkdayInfo(
            holiday="",
            business_day=True,
            previous_business_day=date(2026, 2, 24),
        ),
    }
