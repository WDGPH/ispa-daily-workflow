from __future__ import annotations

import sys
import unittest
from datetime import date
from pathlib import Path

import polars as pl

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_ROOT))

from panorama_compliance.reference import SchoolRecord, SchoolReference  # noqa: E402
from panorama_compliance.domain.pear.intake import (  # noqa: E402
    FooterMetadata,
    LandingReport,
    REPORT_OVERDUE,
    transform_report,
)


def _reference() -> SchoolReference:
    record = SchoolRecord(
        school_name="ALPHA SCHOOL",
        school_id="1001",
        level="ELEMENTARY",
        wave="ELEMENTARY1",
        fq_group="GROUP1",
    )
    return SchoolReference(
        by_id={"1001": record},
        by_name={record.school_name: record},
        secondary_labels=set(),
    )


class TestPearOverdueDedupe(unittest.TestCase):
    def test_overdue_duplicates_warn_and_dedupe_before_processed(self) -> None:
        landing = LandingReport(
            path=Path("20260206_overdue_input.xlsx"),
            report_type=REPORT_OVERDUE,
            title_text="Forecast Query Overdue",
            footer=FooterMetadata(
                report_date=date(2026, 2, 6),
                report_time="11:17:20",
                page_token="1 of 1",
                reported_total_count=None,
            ),
            data_start_row=1,
            data_end_row=3,
            landing_frame=pl.DataFrame(
                {
                    "School Type": ["Elementary", "Elementary"],
                    "School Name": ["ALPHA SCHOOL - 1001", "ALPHA SCHOOL - 1001"],
                    "School City": ["City", "City"],
                    "School Board Name": ["Board", "Board"],
                    "Report Date": ["2026-02-06", "2026-02-06"],
                    "Query Id": ["1", "1"],
                    "Query Name": ["Q", "Q"],
                    "Remaining Overdue": ["0000000001", "0000000001"],
                    "Birth Year": ["2012", "2012"],
                    "First Name": ["alice", "A2"],
                    "Last Name": ["smith", "B2"],
                    "Date of Birth": ["2012-01-01", "2012-01-01"],
                    "Gender": ["F", "F"],
                    "Repeater": ["mmr; tdap", "MMR"],
                }
            ),
            source_rows=[
                {
                    "School Name": "ALPHA SCHOOL - 1001",
                    "Remaining Overdue": "0000000001",
                    "First Name": "alice",
                    "Last Name": "smith",
                    "Date of Birth": "2012-01-01",
                    "Repeater": "mmr; tdap",
                },
                {
                    "School Name": "ALPHA SCHOOL - 1001",
                    "Remaining Overdue": "0000000001",
                    "First Name": "A2",
                    "Last Name": "B2",
                    "Date of Birth": "2012-01-01",
                    "Repeater": "MMR",
                },
            ],
            canonical_filename="20260206_overdue_list_pear.xlsx",
            warnings=(),
        )

        processed = transform_report(landing, reference=_reference())
        self.assertEqual(processed.processed_frame.height, 1)
        self.assertEqual(
            processed.processed_frame.get_column("first_name").to_list(),
            ["ALICE"],
        )
        self.assertEqual(
            processed.processed_frame.get_column("last_name").to_list(),
            ["SMITH"],
        )
        self.assertEqual(
            processed.processed_frame.get_column("overdue_agents").to_list(),
            ["MMR; TDAP"],
        )
        self.assertEqual(len(processed.report_warnings), 1)
        self.assertIn("duplicate_keys=1", processed.report_warnings[0])
        self.assertIn("removed_rows=1", processed.report_warnings[0])
        self.assertIn("0000000001", processed.report_warnings[0])


if __name__ == "__main__":
    unittest.main()
