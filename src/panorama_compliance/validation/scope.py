from __future__ import annotations

from dataclasses import dataclass
import re


ALL_SCOPE_TOKEN = "ALL"
ALLOWED_WAVES = {"ELEMENTARY1", "ELEMENTARY2", "SECONDARY1"}
ALLOWED_LEVELS = {"ELEMENTARY", "SECONDARY"}


@dataclass(frozen=True)
class ScopeSelection:
    dimension: str
    raw_value: str
    normalized_value: str
    is_all: bool

    @property
    def label(self) -> str:
        return f"{self.dimension}={self.raw_value}"


def split_filter_values(values: list[str]) -> list[str]:
    output: list[str] = []
    for value in values:
        for part in str(value).split(","):
            part = part.strip()
            if part:
                output.append(part)
    return output


def _normalize_ref_value(raw_value: str) -> str:
    return re.sub(r"\s+", "", raw_value).upper()


def _normalize_scope_values(
    values: list[str],
    *,
    arg_name: str,
    allowed_values: set[str],
) -> set[str]:
    allowed = {
        _normalize_ref_value(value) for value in allowed_values if str(value).strip()
    }
    normalized = {_normalize_ref_value(value) for value in split_filter_values(values)}
    if not normalized:
        return set()
    if ALL_SCOPE_TOKEN in normalized:
        if len(normalized) > 1:
            raise ValueError(
                f"{arg_name} cannot combine {ALL_SCOPE_TOKEN} with specific values"
            )
        return set()
    invalid = sorted(value for value in normalized if value not in allowed)
    if invalid:
        raise ValueError(
            f"{arg_name} contains unsupported values: {invalid}. "
            f"Allowed values: {sorted(allowed)}"
        )
    return normalized


def normalize_wave_filter_values(
    values: list[str],
    *,
    arg_name: str = "--wave",
    allowed_values: set[str] | None = None,
) -> set[str]:
    return _normalize_scope_values(
        values,
        arg_name=arg_name,
        allowed_values=allowed_values if allowed_values is not None else ALLOWED_WAVES,
    )


def normalize_level_filter_values(
    values: list[str],
    *,
    arg_name: str = "--level",
    allowed_values: set[str] | None = None,
) -> set[str]:
    return _normalize_scope_values(
        values,
        arg_name=arg_name,
        allowed_values=allowed_values if allowed_values is not None else ALLOWED_LEVELS,
    )


def normalize_school_id_filter_values(values: list[str]) -> set[str]:
    normalized: set[str] = set()
    for value in split_filter_values(values):
        digits = re.sub(r"\D", "", value)
        if digits:
            normalized.add(digits)
    return normalized


def normalize_wave_scope_value(
    value: str,
    *,
    allowed_values: set[str] | None = None,
) -> tuple[str, bool]:
    cleaned = str(value).strip()
    normalized = _normalize_ref_value(cleaned)
    if normalized == ALL_SCOPE_TOKEN:
        return ALL_SCOPE_TOKEN, True
    allowed = (
        {
            _normalize_ref_value(candidate)
            for candidate in allowed_values
            if str(candidate).strip()
        }
        if allowed_values is not None
        else ALLOWED_WAVES
    )
    if normalized not in allowed:
        raise ValueError(
            f"--wave must be one of {sorted(allowed)} or {ALL_SCOPE_TOKEN!r}"
        )
    return normalized, False


def normalize_level_scope_value(
    value: str,
    *,
    allowed_values: set[str] | None = None,
) -> tuple[str, bool]:
    cleaned = str(value).strip()
    normalized = _normalize_ref_value(cleaned)
    if normalized == ALL_SCOPE_TOKEN:
        return ALL_SCOPE_TOKEN, True
    allowed = (
        {
            _normalize_ref_value(candidate)
            for candidate in allowed_values
            if str(candidate).strip()
        }
        if allowed_values is not None
        else ALLOWED_LEVELS
    )
    if normalized not in allowed:
        raise ValueError(
            f"--level must be one of {sorted(allowed)} or {ALL_SCOPE_TOKEN!r}"
        )
    return normalized, False


def normalize_school_scope_value(value: str) -> tuple[str, bool]:
    cleaned = str(value).strip()
    if cleaned.upper() == ALL_SCOPE_TOKEN:
        return ALL_SCOPE_TOKEN, True
    digits = re.sub(r"\D", "", cleaned)
    if not digits:
        raise ValueError(
            f"--school must contain at least one digit or be {ALL_SCOPE_TOKEN!r}"
        )
    return digits, False


def parse_scope_selection(
    *,
    wave: str | None,
    level: str | None,
    school: str | None,
    allowed_waves: set[str] | None = None,
    allowed_levels: set[str] | None = None,
) -> ScopeSelection:
    provided: list[tuple[str, str]] = []
    for dimension, value in (("wave", wave), ("level", level), ("school", school)):
        if value is None:
            continue
        text = str(value).strip()
        if not text:
            raise ValueError(f"--{dimension} requires a non-empty value")
        provided.append((dimension, text))

    if len(provided) != 1:
        raise ValueError("Exactly one of --wave, --level, or --school must be provided")

    dimension, raw_value = provided[0]
    if dimension == "school":
        normalized, is_all = normalize_school_scope_value(raw_value)
    elif dimension == "wave":
        normalized, is_all = normalize_wave_scope_value(
            raw_value,
            allowed_values=allowed_waves,
        )
    else:
        normalized, is_all = normalize_level_scope_value(
            raw_value,
            allowed_values=allowed_levels,
        )
    return ScopeSelection(
        dimension=dimension,
        raw_value=raw_value,
        normalized_value=normalized,
        is_all=is_all,
    )
