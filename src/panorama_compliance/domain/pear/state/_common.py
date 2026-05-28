from __future__ import annotations

import re
from datetime import date, datetime
from typing import TypeAlias

from panorama_compliance.schema import ValidationError

REPORT_SUSPENSION = "suspension_active"
REPORT_OVERDUE = "overdue_active"
REPORT_SUSPENSION_VS_OVERDUE = "suspension_vs_overdue"
REPORT_SUSPENSION_OPERATIONAL = "suspension_operational"

PROCESSED_REPORT_OVERDUE = "overdue_list"
PROCESSED_REPORT_SUSPENSION = "suspension_list"
PROCESSED_REPORT_SUSPENSION_VS_OVERDUE = "suspension_vs_overdue"
PROCESSED_REPORT_SUSPENSION_OPERATIONAL = "suspension_operational"

STATE_NAMES = (
    REPORT_SUSPENSION,
    REPORT_OVERDUE,
    REPORT_SUSPENSION_VS_OVERDUE,
    REPORT_SUSPENSION_OPERATIONAL,
)

_SUSPENSION_INPUT_PATTERN = re.compile(
    r"(?P<date>\d{8})_suspension_list_(?P<suffix>secondary|elementary)\.parquet$"
)
_OVERDUE_INPUT_PATTERN = re.compile(r"(?P<date>\d{8})_overdue_list_pear\.parquet$")
_ACTION_INPUT_PATTERN = re.compile(r"(?P<date>\d{8})_suspension_vs_overdue\.parquet$")
_WAVE_SLICED_PROCESSED_PATTERN = re.compile(
    r"(?P<date>\d{8})_pear_(?P<report>overdue_list|suspension_list|suspension_vs_overdue|suspension_operational)_(?P<slice>[a-z0-9_]+)\.parquet$"
)
_STATE_OUTPUT_PATTERN = re.compile(
    r"(?P<date>\d{8})_pear_(?P<slice>.+)_(?P<state>suspension_active|overdue_active|suspension_vs_overdue|suspension_operational)\.parquet$"
)

_INPUT_SCHEMA_BY_STATE = {
    REPORT_SUSPENSION: "processed.pear.suspension",
    REPORT_OVERDUE: "processed.pear.overdue",
    REPORT_SUSPENSION_VS_OVERDUE: "processed.pear.suspension_vs_overdue",
}

_STATE_COLUMNS = {
    REPORT_SUSPENSION: [
        "client_id",
        "school_id",
        "school_name",
        "first_name",
        "last_name",
        "date_of_birth",
        "rescind_date",
        "level",
        "wave",
    ],
    REPORT_OVERDUE: [
        "client_id",
        "school_id",
        "school_name",
        "first_name",
        "last_name",
        "date_of_birth",
        "overdue_agents",
        "level",
        "wave",
    ],
    REPORT_SUSPENSION_VS_OVERDUE: [
        "client_id",
        "school_id",
        "school_name",
        "first_name",
        "last_name",
        "date_of_birth",
        "action_required",
        "action_date",
        "level",
        "wave",
    ],
    REPORT_SUSPENSION_OPERATIONAL: [
        "client_id",
        "school_id",
        "school_name",
        "first_name",
        "last_name",
        "date_of_birth",
        "rescind_date",
        "level",
        "wave",
    ],
}

_ACTION_REQUIRED_VALUES = {"delete", "rescind"}
_RUN_DATE_FMT = "%Y%m%d"
_DISAPPEARANCE_EVIDENCE_COLUMNS = [
    "client_id",
    "school_id",
    "school_name",
    "first_name",
    "last_name",
    "date_of_birth",
    "rescind_date",
    "level",
    "wave",
    "action_required",
    "action_date",
    "mapped_action",
    "mapped_action_date",
    "evidence_source",
    "resolution_status",
    "current_suspension_date",
    "previous_suspension_date",
]

RescindPatchSummary: TypeAlias = dict[str, int | list[str]]


def _parse_date_token(token: str, *, label: str) -> date:
    try:
        return datetime.strptime(token, _RUN_DATE_FMT).date()
    except ValueError as exc:
        raise ValidationError(
            f"Invalid {label} date token {token!r}; expected YYYYMMDD"
        ) from exc


def _format_date_token(value: date) -> str:
    return value.strftime(_RUN_DATE_FMT)
