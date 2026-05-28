from __future__ import annotations

import re

REPORT_SUSPENSION = "suspension_list"
REPORT_SUSPENSION_VS_OVERDUE = "suspension_vs_overdue"
REPORT_OVERDUE = "overdue_summary"

REPORT_ORDER = (REPORT_SUSPENSION, REPORT_SUSPENSION_VS_OVERDUE, REPORT_OVERDUE)

CANONICAL_FILENAME_PATTERNS: dict[str, re.Pattern[str]] = {
    REPORT_SUSPENSION: re.compile(
        r"^(?P<date>\d{8})_suspension_list_(?:elementary|secondary)\.xlsx$",
        re.IGNORECASE,
    ),
    REPORT_SUSPENSION_VS_OVERDUE: re.compile(
        r"^(?P<date>\d{8})_suspension_vs_overdue\.xlsx$",
        re.IGNORECASE,
    ),
    REPORT_OVERDUE: re.compile(
        r"^(?P<date>\d{8})_overdue_list_pear\.xlsx$",
        re.IGNORECASE,
    ),
}

EXPECTED_HEADERS: dict[str, list[str]] = {
    REPORT_SUSPENSION: [
        "School Name",
        "School Id",
        "Last Name",
        "First Name",
        "Date of Birth",
        "Client Id",
        "Suspension Rescind Date",
    ],
    REPORT_SUSPENSION_VS_OVERDUE: [
        "School Name",
        "Last Name",
        "First Name",
        "Date of Birth",
        "ClientID",
        "Suspension Effective From",
        "Suspension Delete Reason",
        "Suspension Rescind Date",
        "Overdue Student",
    ],
    REPORT_OVERDUE: [
        "School Type",
        "School Name",
        "School City",
        "School Board Name",
        "Report Date",
        "Query Id",
        "Query Name",
        "Remaining Overdue",
        "Birth Year",
        "First Name",
        "Last Name",
        "Date of Birth",
        "Gender",
        "Repeater",
    ],
}

HEADER_ALIASES: dict[str, dict[str, list[str]]] = {
    REPORT_SUSPENSION: {
        "School Name": ["School Name"],
        "School Id": ["School Id", "School ID"],
        "Last Name": ["Last Name"],
        "First Name": ["First Name"],
        "Date of Birth": ["Date of Birth"],
        "Client Id": ["Client Id", "Client ID", "ClientID"],
        "Suspension Rescind Date": ["Suspension Rescind Date"],
    },
    REPORT_SUSPENSION_VS_OVERDUE: {
        "School Name": ["School Name"],
        "Last Name": ["Last Name"],
        "First Name": ["First Name"],
        "Date of Birth": ["Date of Birth"],
        "ClientID": ["ClientID", "Client Id", "Client ID"],
        "Suspension Effective From": ["Suspension Effective From"],
        "Suspension Delete Reason": ["Suspension Delete Reason"],
        "Suspension Rescind Date": ["Suspension Rescind Date"],
        "Overdue Student": ["Overdue Student"],
    },
    REPORT_OVERDUE: {
        "School Type": ["School Type"],
        "School Name": ["School Name"],
        "School City": ["School City"],
        "School Board Name": ["School Board Name"],
        "Report Date": ["Report Date"],
        "Query Id": ["Query Id", "Query ID"],
        "Query Name": ["Query Name"],
        "Remaining Overdue": ["Remaining Overdue"],
        "Birth Year": ["Birth Year"],
        "First Name": ["First Name"],
        "Last Name": ["Last Name"],
        "Date of Birth": ["Date of Birth"],
        "Gender": ["Gender"],
        "Repeater": ["Repeater"],
    },
}

LANDING_SCHEMA_BY_REPORT = {
    REPORT_SUSPENSION: "landing.pear.suspension",
    REPORT_SUSPENSION_VS_OVERDUE: "landing.pear.suspension_vs_overdue",
    REPORT_OVERDUE: "landing.pear.overdue",
}

PROCESSED_SCHEMA_BY_REPORT = {
    REPORT_SUSPENSION: "processed.pear.suspension",
    REPORT_SUSPENSION_VS_OVERDUE: "processed.pear.suspension_vs_overdue",
    REPORT_OVERDUE: "processed.pear.overdue",
}

CLIENT_ID_PATTERN = re.compile(r"^[0-9]{10}$")
PAGE_TOKEN_PATTERN = re.compile(r"^\d+\s+of\s+\d+$", re.IGNORECASE)
