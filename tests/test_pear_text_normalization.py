from __future__ import annotations

import sys
import unittest
from datetime import date
from pathlib import Path

import polars as pl

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_ROOT))

from ispa_daily_workflow.domain.pear.intake import (
    REPORT_SUSPENSION,
    REPORT_SUSPENSION_VS_OVERDUE,
    FooterMetadata,
    LandingReport,
    transform_report,
)
from tests.reference_factories import alpha_school_reference


class TestPearTextNormalization(unittest.TestCase):
    def test_suspension_transform_uppercases_name_fields(self) -> None:
        reference = alpha_school_reference(school_name="ALPHA SCHOOL")
        landing = LandingReport(
            path=Path("20260225_suspension_input.xlsx"),
            report_type=REPORT_SUSPENSION,
            title_text="On Suspensions List_Elementary",
            footer=FooterMetadata(
                report_date=date(2026, 2, 25),
                report_time="08:00:00",
                page_token="1 of 1",
                reported_total_count=None,
            ),
            data_start_row=1,
            data_end_row=2,
            landing_frame=pl.DataFrame(
                {
                    "School Name": ["ALPHA SCHOOL - 1001"],
                    "School Id": ["1001"],
                    "Last Name": ["doE"],
                    "First Name": ["jAnE"],
                    "Date of Birth": ["2012-01-01"],
                    "Client Id": ["0000000001"],
                    "Suspension Rescind Date": [None],
                }
            ),
            source_rows=[
                {
                    "School Name": "ALPHA SCHOOL - 1001",
                    "School Id": "1001",
                    "Last Name": "doE",
                    "First Name": "jAnE",
                    "Date of Birth": "2012-01-01",
                    "Client Id": "0000000001",
                    "Suspension Rescind Date": None,
                }
            ],
            canonical_filename="20260225_suspension_list_elementary.xlsx",
            warnings=(),
        )

        processed = transform_report(landing, reference=reference)
        self.assertEqual(
            processed.processed_frame.get_column("school_name").to_list(),
            ["ALPHA SCHOOL"],
        )
        self.assertEqual(
            processed.processed_frame.get_column("first_name").to_list(),
            ["JANE"],
        )
        self.assertEqual(
            processed.processed_frame.get_column("last_name").to_list(),
            ["DOE"],
        )

    def test_suspension_vs_overdue_transform_uppercases_name_fields(self) -> None:
        reference = alpha_school_reference(school_name="ALPHA SCHOOL")
        landing = LandingReport(
            path=Path("20260225_suspension_vs_overdue_input.xlsx"),
            report_type=REPORT_SUSPENSION_VS_OVERDUE,
            title_text="ReminderRecallSuspension_NeedSuspensionDeleted_Detail",
            footer=FooterMetadata(
                report_date=date(2026, 2, 25),
                report_time="08:00:00",
                page_token="1 of 1",
                reported_total_count=None,
            ),
            data_start_row=1,
            data_end_row=2,
            landing_frame=pl.DataFrame(
                {
                    "School Name": ["ALPHA SCHOOL - 1001"],
                    "Last Name": ["smITh"],
                    "First Name": ["joHn"],
                    "Date of Birth": ["2011-01-01"],
                    "ClientID": ["0000000002"],
                    "Suspension Effective From": ["2026-02-25"],
                    "Suspension Delete Reason": [None],
                    "Suspension Rescind Date": [None],
                    "Overdue Student": ["Y"],
                }
            ),
            source_rows=[
                {
                    "School Name": "ALPHA SCHOOL - 1001",
                    "Last Name": "smITh",
                    "First Name": "joHn",
                    "Date of Birth": "2011-01-01",
                    "ClientID": "0000000002",
                    "Suspension Effective From": "2026-02-25",
                    "Suspension Delete Reason": None,
                    "Suspension Rescind Date": None,
                    "Overdue Student": "Y",
                }
            ],
            canonical_filename="20260225_suspension_vs_overdue.xlsx",
            warnings=(),
        )

        processed = transform_report(
            landing,
            reference=reference,
            wave_windows=reference.wave_windows,
        )
        self.assertEqual(
            processed.processed_frame.get_column("school_name").to_list(),
            ["ALPHA SCHOOL"],
        )
        self.assertEqual(
            processed.processed_frame.get_column("first_name").to_list(),
            ["JOHN"],
        )
        self.assertEqual(
            processed.processed_frame.get_column("last_name").to_list(),
            ["SMITH"],
        )


if __name__ == "__main__":
    unittest.main()
