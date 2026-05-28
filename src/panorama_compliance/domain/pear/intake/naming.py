from __future__ import annotations

import re
from datetime import date, datetime
from pathlib import Path
from typing import Any

from panorama_compliance.reference import SchoolReference, parse_school_name_and_id
from panorama_compliance.schema import ValidationError

from .constants import (
    CANONICAL_FILENAME_PATTERNS,
    REPORT_OVERDUE,
    REPORT_SUSPENSION,
    REPORT_SUSPENSION_VS_OVERDUE,
)
from .models import LandingReport
from .primitives import is_blank_value


def parse_canonical_report_date(path: Path, *, report_type: str) -> date:
    pattern = CANONICAL_FILENAME_PATTERNS.get(report_type)
    if pattern is None:
        raise ValidationError(
            f"{path.name}: unsupported report type for canonical filename parsing"
        )
    match = pattern.match(path.name)
    if match is None:
        raise ValidationError(
            f"{path.name}: expected canonical filename for report_type={report_type}"
        )
    date_token = match.group("date")
    try:
        return datetime.strptime(date_token, "%Y%m%d").date()
    except ValueError as exc:
        raise ValidationError(
            f"{path.name}: invalid canonical date token {date_token!r}"
        ) from exc


def canonical_filename(
    *,
    report_type: str,
    title_text: str,
    report_date: date,
    source_name: str | None = None,
) -> str:
    date_token = report_date.strftime("%Y%m%d")
    if report_type == REPORT_SUSPENSION:
        return suspension_canonical_filename(
            report_date=report_date,
            suffix=title_suspension_suffix(title_text, source_name=source_name),
        )
    if report_type == REPORT_SUSPENSION_VS_OVERDUE:
        return f"{date_token}_suspension_vs_overdue.xlsx"
    if report_type == REPORT_OVERDUE:
        return f"{date_token}_overdue_list_pear.xlsx"
    raise ValidationError(
        f"Unsupported report type for canonical filename: {report_type}"
    )


def resolve_suspension_canonical_filename(
    landing: LandingReport,
    *,
    reference: SchoolReference,
) -> tuple[str, str, str | None]:
    if landing.report_type != REPORT_SUSPENSION:
        raise ValidationError(
            f"{landing.path.name}: resolve_suspension_canonical_filename requires report_type=suspension_list"
        )
    suffix, suffix_warning = determine_suspension_suffix(
        landing,
        reference=reference,
    )
    filename = suspension_canonical_filename(
        report_date=landing.footer.report_date,
        suffix=suffix,
    )
    return filename, suffix, suffix_warning


def title_suspension_suffix(
    title_text: str,
    *,
    source_name: str | None = None,
) -> str:
    normalized_title = re.sub(r"[^a-z0-9]+", " ", title_text.lower()).strip()
    if re.search(r"\bon\s+suspensions\s+list\s+elementary\b", normalized_title):
        return "elementary"
    if re.search(r"\bon\s+suspensions\s+list\s+secondary\b", normalized_title):
        return "secondary"

    has_elementary = "elementary" in normalized_title
    has_secondary = "secondary" in normalized_title
    if has_elementary and not has_secondary:
        return "elementary"
    if has_secondary and not has_elementary:
        return "secondary"
    if has_elementary and has_secondary:
        elementary_index = normalized_title.find("elementary")
        secondary_index = normalized_title.find("secondary")
        if elementary_index < secondary_index:
            return "elementary"
        if secondary_index < elementary_index:
            return "secondary"

    if source_name:
        normalized_source = re.sub(r"[^a-z0-9]+", " ", source_name.lower()).strip()
        if " elementary " in f" {normalized_source} ":
            return "elementary"
        if " secondary " in f" {normalized_source} ":
            return "secondary"

    return "elementary"


def suspension_canonical_filename(*, report_date: date, suffix: str) -> str:
    date_token = report_date.strftime("%Y%m%d")
    return f"{date_token}_suspension_list_{suffix}.xlsx"


def determine_suspension_suffix(
    landing: LandingReport,
    *,
    reference: SchoolReference,
) -> tuple[str, str | None]:
    if landing.report_type != REPORT_SUSPENSION:
        return title_suspension_suffix(
            landing.title_text,
            source_name=landing.path.name,
        ), None

    fill_school_name: Any = None
    level_counts = {"ELEMENTARY": 0, "SECONDARY": 0}
    for row in landing.source_rows:
        school_name_raw = row.get("School Name")
        if not is_blank_value(school_name_raw):
            fill_school_name = school_name_raw
        if is_blank_value(fill_school_name):
            continue
        _school_name, _school_id, level, _wave = _resolve_school(
            fill_school_name,
            reference,
            landing.path,
        )
        if level in level_counts:
            level_counts[level] += 1

    has_elementary = level_counts["ELEMENTARY"] > 0
    has_secondary = level_counts["SECONDARY"] > 0
    if has_elementary and not has_secondary:
        return "elementary", None
    if has_secondary and not has_elementary:
        return "secondary", None

    title_suffix = title_suspension_suffix(
        landing.title_text,
        source_name=landing.path.name,
    )
    if has_elementary and has_secondary:
        if level_counts["ELEMENTARY"] > level_counts["SECONDARY"]:
            return (
                "elementary",
                "Suspension report included mixed levels; suffix selected by dominant "
                f"school-reference level counts ELEMENTARY={level_counts['ELEMENTARY']} "
                f"SECONDARY={level_counts['SECONDARY']}",
            )
        if level_counts["SECONDARY"] > level_counts["ELEMENTARY"]:
            return (
                "secondary",
                "Suspension report included mixed levels; suffix selected by dominant "
                f"school-reference level counts ELEMENTARY={level_counts['ELEMENTARY']} "
                f"SECONDARY={level_counts['SECONDARY']}",
            )
        return (
            title_suffix,
            "Suspension report included balanced mixed levels; suffix fell back to title text",
        )

    return (
        title_suffix,
        "Suspension report level distribution could not be derived from school reference; "
        "suffix fell back to title text",
    )


def _resolve_school(
    school_name_raw: Any,
    reference: SchoolReference,
    source_path: Path,
) -> tuple[str, str, str, str]:
    school_name, school_id = parse_school_name_and_id(school_name_raw, None)
    if not school_id:
        raise ValidationError(
            f"{source_path.name}: unable to parse school_id from School Name"
        )
    record = reference.by_id.get(school_id)
    if record is None:
        raise ValidationError(
            f"{source_path.name}: school_id {school_id} not found in school reference"
        )
    return record.school_name, school_id, record.level, record.wave
