from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path


SCHOOL_NAME_SPLIT = " - "


@dataclass(frozen=True)
class WaveWindow:
    applied_date: date
    suspension_window_start: date
    suspension_window_end: date


@dataclass(frozen=True)
class SchoolRecord:
    school_name: str
    school_id: str | None
    level: str
    wave: str
    fq_group: str
    sharepoint_folder: str | None = None
    suspension_applied_date: date | None = None
    suspension_window_start: date | None = None
    suspension_window_end: date | None = None


@dataclass(frozen=True)
class SchoolReference:
    by_id: dict[str, SchoolRecord]
    by_name: dict[str, SchoolRecord]
    secondary_labels: set[str]
    wave_windows: dict[str, WaveWindow] = field(default_factory=dict)


def normalize_ref_value(value: str | None) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", "", str(value).strip()).upper()


def parse_school_name_and_id(
    raw_name: object, raw_id: object
) -> tuple[str, str | None]:
    school_name = ""
    school_id: str | None = None

    if raw_name is not None:
        text = str(raw_name).strip()
        if text:
            if SCHOOL_NAME_SPLIT in text and (
                raw_id is None or str(raw_id).strip() == ""
            ):
                left, right = text.rsplit(SCHOOL_NAME_SPLIT, 1)
                digits = re.sub(r"\D", "", right)
                if digits:
                    school_id = digits
                    text = left
            school_name = text.strip().upper().replace("&", "AND")

    if raw_id is not None and str(raw_id).strip() != "":
        digits = re.sub(r"\D", "", str(raw_id))
        if digits:
            school_id = digits

    return school_name, school_id


def normalize_sharepoint_folder(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    normalized = text.replace("\\", "/")
    parts = [segment.strip() for segment in normalized.split("/") if segment.strip()]
    if not parts:
        return None
    if any(segment in {".", ".."} for segment in parts):
        raise ValueError(f"Invalid sharepoint_folder path segment: {text!r}")
    return "/".join(parts)


def parse_reference_date(value: object, *, label: str) -> date | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return datetime.strptime(text, "%Y-%m-%d").date()
    except ValueError as exc:
        raise ValueError(
            f"Invalid reference value for {label}: {value!r} (expected YYYY-MM-DD)"
        ) from exc


def resolve_sharepoint_folder_for_school(
    reference: SchoolReference, school_label: str
) -> str | None:
    school_name, school_id = parse_school_name_and_id(school_label, None)
    if school_id:
        by_id = reference.by_id.get(school_id)
        if by_id and by_id.sharepoint_folder:
            return by_id.sharepoint_folder
    if school_name:
        by_name = reference.by_name.get(school_name)
        if by_name and by_name.sharepoint_folder:
            return by_name.sharepoint_folder
    return None


def resolve_wave_for_school(
    reference: SchoolReference, school_label: str
) -> str | None:
    school_name, school_id = parse_school_name_and_id(school_label, None)
    if school_id:
        by_id = reference.by_id.get(school_id)
        if by_id and by_id.wave:
            return by_id.wave
    if school_name:
        by_name = reference.by_name.get(school_name)
        if by_name and by_name.wave:
            return by_name.wave
    return None


def resolve_school_record(
    reference: SchoolReference, school_label: str
) -> SchoolRecord | None:
    school_name, school_id = parse_school_name_and_id(school_label, None)
    if school_id:
        by_id = reference.by_id.get(school_id)
        if by_id is not None:
            return by_id
    if school_name:
        return reference.by_name.get(school_name)
    return None


def collect_scope_values(reference: SchoolReference) -> tuple[set[str], set[str]]:
    records = set(reference.by_id.values()) | set(reference.by_name.values())
    waves = {
        normalize_ref_value(record.wave)
        for record in records
        if normalize_ref_value(record.wave)
    }
    levels = {
        normalize_ref_value(record.level)
        for record in records
        if normalize_ref_value(record.level)
    }
    return waves, levels


def load_school_reference(path: Path) -> SchoolReference:
    if not path.exists():
        raise FileNotFoundError(f"Missing reference file: {path}")

    with path.open("r", encoding="utf-8") as handle:
        rows = json.load(handle)
    if not isinstance(rows, list):
        raise ValueError(f"Reference file must be a list: {path}")

    by_id: dict[str, SchoolRecord] = {}
    by_name: dict[str, SchoolRecord] = {}
    secondary_labels: set[str] = set()
    wave_windows: dict[str, WaveWindow] = {}

    for row in rows:
        if not isinstance(row, dict):
            raise ValueError(f"Invalid reference row: {row!r}")

        school_name, school_id = parse_school_name_and_id(
            row.get("school_name"),
            row.get("school_id"),
        )
        suspension_applied_date = parse_reference_date(
            row.get("suspension_applied_date"),
            label="suspension_applied_date",
        )
        suspension_window_start = parse_reference_date(
            row.get("suspension_window_start"),
            label="suspension_window_start",
        )
        suspension_window_end = parse_reference_date(
            row.get("suspension_window_end"),
            label="suspension_window_end",
        )
        suspension_values = (
            suspension_applied_date,
            suspension_window_start,
            suspension_window_end,
        )
        provided_suspension_values = sum(
            value is not None for value in suspension_values
        )
        if provided_suspension_values not in {0, 3}:
            raise ValueError(
                "Reference row must include all or none of suspension window fields "
                "(suspension_applied_date, suspension_window_start, "
                f"suspension_window_end): {row!r}"
            )

        record = SchoolRecord(
            school_name=school_name,
            school_id=school_id,
            level=normalize_ref_value(row.get("level")),
            wave=normalize_ref_value(row.get("wave")),
            fq_group=normalize_ref_value(row.get("fq_group")),
            sharepoint_folder=normalize_sharepoint_folder(row.get("sharepoint_folder")),
            suspension_applied_date=suspension_applied_date,
            suspension_window_start=suspension_window_start,
            suspension_window_end=suspension_window_end,
        )

        if record.wave:
            if provided_suspension_values == 3:
                assert suspension_applied_date is not None
                assert suspension_window_start is not None
                assert suspension_window_end is not None
                candidate_window = WaveWindow(
                    applied_date=suspension_applied_date,
                    suspension_window_start=suspension_window_start,
                    suspension_window_end=suspension_window_end,
                )
                existing_window = wave_windows.get(record.wave)
                if existing_window and existing_window != candidate_window:
                    raise ValueError(
                        f"Conflicting suspension window metadata for wave {record.wave}"
                    )
                wave_windows[record.wave] = candidate_window
            elif record.wave in wave_windows:
                raise ValueError(
                    "Missing suspension window metadata for row in wave "
                    f"{record.wave}; all rows in a wave must be consistent"
                )

        if school_id:
            existing = by_id.get(school_id)
            if existing and existing != record:
                raise ValueError(
                    f"Conflicting reference rows for school_id {school_id}"
                )
            by_id[school_id] = record

        if school_name:
            existing = by_name.get(school_name)
            if existing and existing != record:
                raise ValueError(
                    f"Conflicting reference rows for school_name {school_name}"
                )
            by_name[school_name] = record

        if record.level == "SECONDARY" and school_name and school_id:
            secondary_labels.add(f"{school_name} - {school_id}")

    return SchoolReference(
        by_id=by_id,
        by_name=by_name,
        secondary_labels=secondary_labels,
        wave_windows=wave_windows,
    )
