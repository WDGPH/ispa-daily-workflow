from __future__ import annotations

import sys
import unittest
from datetime import date
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_ROOT))

from ispa_daily_workflow.domain.delivery.publish import (
    _final_summary_name_candidates,
    _school_year_final_summary_filename,
    _school_year_suspension_period_complete_filename,
    _terminal_cleanup_regex_for_school,
)


class TestSharepointFinalSummaryNaming(unittest.TestCase):
    def test_school_year_final_summary_filename_uses_september_boundary(self) -> None:
        school = "ALPHA SCHOOL - 1001"
        self.assertEqual(
            _school_year_final_summary_filename(school, date(2026, 2, 25)),
            "2025_2026_ALPHA_SCHOOL_1001_ISPA_FINAL_SUMMARY.pdf",
        )
        self.assertEqual(
            _school_year_final_summary_filename(school, date(2026, 9, 1)),
            "2026_2027_ALPHA_SCHOOL_1001_ISPA_FINAL_SUMMARY.pdf",
        )

    def test_final_summary_candidates_use_school_year_name_only(self) -> None:
        candidates = _final_summary_name_candidates(
            "ALPHA SCHOOL - 1001",
            date(2026, 2, 25),
        )
        self.assertEqual(
            candidates,
            {
                "2025_2026_ALPHA_SCHOOL_1001_ISPA_FINAL_SUMMARY.pdf",
                "2025_2026_ALPHA_SCHOOL_1001_ISPA_SUSPENSION_PERIOD_COMPLETE.pdf",
            },
        )

    def test_school_year_suspension_period_complete_filename_uses_september_boundary(
        self,
    ) -> None:
        school = "ALPHA SCHOOL - 1001"
        self.assertEqual(
            _school_year_suspension_period_complete_filename(school, date(2026, 2, 25)),
            "2025_2026_ALPHA_SCHOOL_1001_ISPA_SUSPENSION_PERIOD_COMPLETE.pdf",
        )

    def test_school_year_boundary_is_configurable(self) -> None:
        school = "ALPHA SCHOOL - 1001"
        self.assertEqual(
            _school_year_final_summary_filename(
                school,
                date(2026, 2, 25),
                school_year_start_month=1,
            ),
            "2026_2027_ALPHA_SCHOOL_1001_ISPA_FINAL_SUMMARY.pdf",
        )

    def test_terminal_cleanup_regex_targets_same_school_year_terminal_files(
        self,
    ) -> None:
        regex = _terminal_cleanup_regex_for_school(
            school_label="ALPHA SCHOOL - 1001",
            terminal_status="suspension_period_complete",
            run_date=date(2026, 2, 25),
        )
        self.assertIsNotNone(regex)
        import re

        pattern = re.compile(regex or "")
        self.assertTrue(
            pattern.search("2025_2026_ALPHA_SCHOOL_1001_ISPA_FINAL_SUMMARY.pdf")
        )
        self.assertTrue(
            pattern.search(
                "2025_2026_ALPHA_SCHOOL_1001_ISPA_SUSPENSION_PERIOD_COMPLETE.pdf"
            )
        )
        self.assertFalse(
            pattern.search("20260225_ALPHA_SCHOOL_1001_SUSPENSION_LIST.pdf")
        )


if __name__ == "__main__":
    unittest.main()
