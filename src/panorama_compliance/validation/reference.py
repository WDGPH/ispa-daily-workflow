from __future__ import annotations

from dataclasses import dataclass

import polars as pl

from panorama_compliance.normalize import parse_year_value
from panorama_compliance.reference import SchoolReference, parse_school_name_and_id
from panorama_compliance.schema import ValidationError


@dataclass(frozen=True)
class ReferenceSliceClassification:
    level: str
    wave: str
    fq_group: str | None = None
    secondary_school_id: str | None = None
    cohort: str | None = None


def determine_secondary_birth_cohort(
    frame: pl.DataFrame,
    *,
    label: str,
    dob_column: str = "date_of_birth",
) -> str:
    if dob_column not in frame.columns:
        raise ValidationError(f"{label} missing {dob_column}")
    years = [
        parse_year_value(value) for value in frame.get_column(dob_column).to_list()
    ]
    if any(year is None for year in years):
        missing = sum(1 for year in years if year is None)
        raise ValidationError(f"{label} has {missing} invalid {dob_column} rows")
    assert years
    if min(years) >= 2010:
        return "2010_and_later"
    if max(years) <= 2009:
        return "2009_and_earlier"
    raise ValidationError(f"{label} mixes 2010_and_later and 2009_and_earlier cohorts")


def classify_reference_slice(
    frame: pl.DataFrame,
    *,
    label: str,
    reference: SchoolReference,
    school_name_column: str = "school_name",
    school_id_column: str = "school_id",
) -> ReferenceSliceClassification:
    if frame.is_empty():
        raise ValidationError(f"{label} is empty")
    if school_name_column not in frame.columns:
        raise ValidationError(f"{label} missing {school_name_column}")

    working = frame
    if school_id_column not in working.columns:
        working = working.with_columns(
            pl.lit(None, dtype=pl.Utf8).alias(school_id_column)
        )

    unique_schools = working.select([school_name_column, school_id_column]).unique()
    levels: set[str] = set()
    waves: set[str] = set()
    fq_groups: set[str] = set()
    secondary_ids: set[str] = set()

    for row in unique_schools.iter_rows(named=True):
        school_name, school_id = parse_school_name_and_id(
            row.get(school_name_column),
            row.get(school_id_column),
        )
        record = None
        if school_id and school_id in reference.by_id:
            record = reference.by_id[school_id]
        elif school_name and school_name in reference.by_name:
            record = reference.by_name[school_name]
        if record is None:
            raise ValidationError(
                f"{label} includes school not in reference: "
                f"{school_name or 'UNKNOWN'} ({school_id or 'no id'})"
            )
        levels.add(record.level)
        waves.add(record.wave)
        fq_groups.add(record.fq_group)
        if record.level == "SECONDARY" and record.school_id:
            secondary_ids.add(record.school_id)

    if len(levels) != 1 or len(waves) != 1:
        raise ValidationError(
            f"{label} spans multiple levels/waves: levels={sorted(levels)} waves={sorted(waves)}"
        )

    level = next(iter(levels))
    wave = next(iter(waves))
    if level == "ELEMENTARY":
        if len(fq_groups) != 1:
            raise ValidationError(
                f"{label} spans multiple fq_groups: {sorted(fq_groups)}"
            )
        return ReferenceSliceClassification(
            level=level,
            wave=wave,
            fq_group=next(iter(fq_groups)),
        )

    if level == "SECONDARY":
        if len(secondary_ids) != 1:
            raise ValidationError(f"{label} spans multiple secondary schools")
        return ReferenceSliceClassification(
            level=level,
            wave=wave,
            secondary_school_id=next(iter(secondary_ids)),
            cohort=determine_secondary_birth_cohort(working, label=label),
        )

    raise ValidationError(f"{label} has unsupported level: {level}")
