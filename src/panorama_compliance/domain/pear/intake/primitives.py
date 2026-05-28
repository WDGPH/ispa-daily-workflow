from __future__ import annotations

import re
from datetime import date, datetime, time
from pathlib import Path
from typing import Any

from openpyxl.utils.datetime import from_excel

from panorama_compliance.schema import ValidationError


def header_token(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", text.lower())


def cell_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(value, date):
        return value.strftime("%Y-%m-%d")
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def to_scalar(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return value
    if isinstance(value, time):
        return value.strftime("%H:%M:%S")
    text = cell_text(value)
    return text if text else None


def is_blank_value(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return value.strip() == ""
    return False


def row_is_blank(row: list[Any]) -> bool:
    return all(is_blank_value(value) for value in row)


def parse_date_required(value: Any, source_path: Path, label: str) -> date:
    parsed = parse_date_optional(value, source_path, label)
    if parsed is None:
        raise ValidationError(
            f"{source_path.name}: missing required date field {label}"
        )
    return parsed


def parse_date_optional(value: Any, source_path: Path, label: str) -> date | None:
    if is_blank_value(value):
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, (int, float)):
        parsed = from_excel(value)
        if isinstance(parsed, datetime):
            return parsed.date()
        if isinstance(parsed, date):
            return parsed
    text = cell_text(value)
    if not text:
        return None
    for fmt in (
        "%Y-%m-%d",
        "%Y/%m/%d",
        "%m/%d/%Y",
        "%m-%d-%Y",
        "%b %d, %Y",
        "%B %d, %Y",
        "%b %d %Y",
        "%B %d %Y",
    ):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(text).date()
    except ValueError as exc:
        raise ValidationError(
            f"{source_path.name}: unable to parse date for {label}"
        ) from exc


def parse_time_required(value: Any, source_path: Path, label: str) -> str:
    if is_blank_value(value):
        raise ValidationError(
            f"{source_path.name}: missing required time field {label}"
        )
    if isinstance(value, datetime):
        return value.strftime("%H:%M:%S")
    if isinstance(value, time):
        return value.strftime("%H:%M:%S")
    text = cell_text(value)
    if not text:
        raise ValidationError(
            f"{source_path.name}: missing required time field {label}"
        )
    for fmt in ("%I:%M:%S %p", "%I:%M %p", "%H:%M:%S", "%H:%M"):
        try:
            parsed = datetime.strptime(text, fmt)
            return parsed.strftime("%H:%M:%S")
        except ValueError:
            continue
    if ":" in text:
        return text
    raise ValidationError(f"{source_path.name}: unable to parse time for {label}")


def summary_row(row: list[Any]) -> bool:
    for value in row:
        if "overall" in cell_text(value).lower():
            return True
    return False


def extract_int(row: list[Any]) -> int | None:
    for value in row:
        if isinstance(value, (int, float)):
            if int(value) >= 0:
                return int(value)
            continue
        text = cell_text(value)
        if not text:
            continue
        candidate = re.sub(r"[^\d]", "", text)
        if candidate:
            try:
                return int(candidate)
            except ValueError:
                continue
    return None
