from __future__ import annotations

import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

import polars as pl

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_ROOT))

from panorama_compliance.reports.report_writer import write_reports  # noqa: E402
from panorama_compliance.constants import OUTDATED_PDF_PATTERN  # noqa: E402
from panorama_compliance.reference import SchoolRecord, SchoolReference  # noqa: E402
from panorama_compliance.validation.catalog import (  # noqa: E402
    RULE_PREVIOUS_BUSINESS_DAY_ID,
)


class TestReportWriterTemporal(unittest.TestCase):
    @staticmethod
    def _reference_with_closed_suspension_window() -> SchoolReference:
        school = SchoolRecord(
            school_name="ALPHA SCHOOL",
            school_id="1001",
            level="SECONDARY",
            wave="SECONDARY1",
            fq_group="G1",
            suspension_applied_date=date(2026, 2, 1),
            suspension_window_start=date(2026, 2, 10),
            suspension_window_end=date(2026, 2, 20),
        )
        return SchoolReference(
            by_id={"1001": school},
            by_name={"ALPHA SCHOOL": school},
            secondary_labels={"ALPHA SCHOOL - 1001"},
        )

    def test_outdated_pdf_pattern_matches_list_names_only(self) -> None:
        self.assertTrue(OUTDATED_PDF_PATTERN.match("20260225_ALPHA_OVERDUE_LIST.pdf"))
        self.assertFalse(OUTDATED_PDF_PATTERN.match("ALPHA_FINAL_SUMMARY.pdf"))
        self.assertFalse(
            OUTDATED_PDF_PATTERN.match("20260225_ALPHA_ISPA_FINAL_SUMMARY.pdf")
        )
        self.assertFalse(
            OUTDATED_PDF_PATTERN.match(
                "2025_2026_ALPHA_SCHOOL_1001_ISPA_FINAL_SUMMARY.pdf"
            )
        )

    def test_suspension_requires_previous_business_day(self) -> None:
        with self.assertRaisesRegex(ValueError, RULE_PREVIOUS_BUSINESS_DAY_ID):
            write_reports(
                report_type="suspension",
                df=pl.DataFrame(),
                run_date=date(2026, 2, 14),
                prev_business_day=None,
                output_root=PROJECT_ROOT / "output",
                artifacts_root=PROJECT_ROOT / "artifacts",
                logo_path=PROJECT_ROOT / "profile.example" / "logo.pdf",
                typst_bin="typst",
                project_root=PROJECT_ROOT,
                no_compile=True,
                prune_history=False,
                keep_artifacts=False,
                secondary_labels=set(),
            )

    def test_overdue_writes_all_up_to_date_when_target_school_has_zero_rows(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            outputs = write_reports(
                report_type="overdue",
                df=pl.DataFrame(
                    schema={
                        "school_label": pl.Utf8,
                        "last_name": pl.Utf8,
                        "first_name": pl.Utf8,
                        "date_of_birth": pl.Utf8,
                    }
                ),
                run_date=date(2026, 2, 25),
                prev_business_day=None,
                output_root=root / "output",
                artifacts_root=root / "artifacts",
                logo_path=PROJECT_ROOT / "profile.example" / "logo.pdf",
                typst_bin="/bin/true",
                project_root=PROJECT_ROOT,
                no_compile=False,
                prune_history=False,
                keep_artifacts=True,
                secondary_labels=set(),
                target_school_labels=["ALPHA SCHOOL - 1001"],
            )

            self.assertEqual(len(outputs), 1)
            self.assertEqual(outputs[0].counts["overdue"], 0)
            self.assertTrue(
                outputs[0].pdf_path.name.endswith(
                    "_ALPHA_SCHOOL_1001_ISPA_FINAL_SUMMARY.pdf"
                )
            )
            self.assertTrue(outputs[0].pdf_path.name.startswith("2025_2026_"))

            typst_dir = root / "artifacts" / "typst" / "overdue"
            typst_files = list(typst_dir.glob("*.typ"))
            self.assertEqual(len(typst_files), 1)
            content = typst_files[0].read_text(encoding="utf-8")
            self.assertIn("Final Summary", content)
            self.assertIn("All students are up to date", content)
            self.assertNotIn('As of #text(weight: "bold")[2026-02-25]', content)

    def test_suspension_writes_all_up_to_date_when_target_school_has_zero_rows(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            outputs = write_reports(
                report_type="suspension",
                df=pl.DataFrame(
                    schema={
                        "school_label": pl.Utf8,
                        "last_name": pl.Utf8,
                        "first_name": pl.Utf8,
                        "date_of_birth": pl.Utf8,
                        "compliant": pl.Date,
                    }
                ),
                run_date=date(2026, 2, 25),
                prev_business_day=date(2026, 2, 24),
                output_root=root / "output",
                artifacts_root=root / "artifacts",
                logo_path=PROJECT_ROOT / "profile.example" / "logo.pdf",
                typst_bin="/bin/true",
                project_root=PROJECT_ROOT,
                no_compile=False,
                prune_history=False,
                keep_artifacts=True,
                secondary_labels=set(),
                target_school_labels=["ALPHA SCHOOL - 1001"],
            )

            self.assertEqual(len(outputs), 1)
            self.assertEqual(outputs[0].counts["active"], 0)
            self.assertEqual(outputs[0].counts["rescinded"], 0)
            self.assertTrue(
                outputs[0].pdf_path.name.endswith(
                    "_ALPHA_SCHOOL_1001_ISPA_FINAL_SUMMARY.pdf"
                )
            )
            self.assertTrue(outputs[0].pdf_path.name.startswith("2025_2026_"))

            typst_dir = root / "artifacts" / "typst" / "suspension"
            typst_files = list(typst_dir.glob("*.typ"))
            self.assertEqual(len(typst_files), 1)
            content = typst_files[0].read_text(encoding="utf-8")
            self.assertIn("Final Summary", content)
            self.assertIn("All students are up to date", content)
            self.assertNotIn('As of #text(weight: "bold")[2026-02-25]', content)

    def test_suspension_final_summary_includes_latest_historical_rescind_date(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            outputs = write_reports(
                report_type="suspension",
                df=pl.DataFrame(
                    {
                        "school_label": ["ALPHA SCHOOL - 1001"],
                        "last_name": ["DOE"],
                        "first_name": ["JANE"],
                        "date_of_birth": ["2010-01-01"],
                        "compliant": [date(2026, 2, 20)],
                    }
                ),
                run_date=date(2026, 2, 25),
                prev_business_day=date(2026, 2, 24),
                output_root=root / "output",
                artifacts_root=root / "artifacts",
                logo_path=PROJECT_ROOT / "profile.example" / "logo.pdf",
                typst_bin="/bin/true",
                project_root=PROJECT_ROOT,
                no_compile=False,
                prune_history=False,
                keep_artifacts=True,
                secondary_labels=set(),
                target_school_labels=["ALPHA SCHOOL - 1001"],
            )

            self.assertEqual(len(outputs), 1)
            self.assertTrue(
                outputs[0].pdf_path.name.endswith(
                    "_ALPHA_SCHOOL_1001_ISPA_FINAL_SUMMARY.pdf"
                )
            )
            self.assertTrue(outputs[0].pdf_path.name.startswith("2025_2026_"))
            typst_dir = root / "artifacts" / "typst" / "suspension"
            typst_files = list(typst_dir.glob("*.typ"))
            self.assertEqual(len(typst_files), 1)
            content = typst_files[0].read_text(encoding="utf-8")
            self.assertIn("Final Summary", content)
            self.assertIn("2026-02-20", content)

    def test_overdue_writes_suspension_period_complete_notice_after_window_end(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            outputs = write_reports(
                report_type="overdue",
                df=pl.DataFrame(
                    {
                        "school_label": ["ALPHA SCHOOL - 1001"],
                        "last_name": ["DOE"],
                        "first_name": ["JANE"],
                        "date_of_birth": ["2010-01-01"],
                    }
                ),
                run_date=date(2026, 2, 25),
                prev_business_day=None,
                output_root=root / "output",
                artifacts_root=root / "artifacts",
                logo_path=PROJECT_ROOT / "profile.example" / "logo.pdf",
                typst_bin="/bin/true",
                project_root=PROJECT_ROOT,
                no_compile=False,
                prune_history=False,
                keep_artifacts=True,
                secondary_labels={"ALPHA SCHOOL - 1001"},
                target_school_labels=["ALPHA SCHOOL - 1001"],
                reference=self._reference_with_closed_suspension_window(),
            )

            self.assertEqual(len(outputs), 1)
            self.assertEqual(outputs[0].terminal_status, "suspension_period_complete")
            self.assertTrue(
                outputs[0].pdf_path.name.endswith(
                    "_ALPHA_SCHOOL_1001_ISPA_SUSPENSION_PERIOD_COMPLETE.pdf"
                )
            )
            typst_files = list((root / "artifacts" / "typst" / "overdue").glob("*.typ"))
            self.assertEqual(len(typst_files), 1)
            content = typst_files[0].read_text(encoding="utf-8")
            self.assertIn("Suspension Period Complete", content)
            self.assertIn(
                "the ISPA suspension period for this school is complete", content
            )

    def test_suspension_writes_suspension_period_complete_notice_after_window_end(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            outputs = write_reports(
                report_type="suspension",
                df=pl.DataFrame(
                    {
                        "school_label": ["ALPHA SCHOOL - 1001"],
                        "last_name": ["DOE"],
                        "first_name": ["JANE"],
                        "date_of_birth": [date(2010, 1, 1)],
                        "compliant": [None],
                    },
                    schema={
                        "school_label": pl.Utf8,
                        "last_name": pl.Utf8,
                        "first_name": pl.Utf8,
                        "date_of_birth": pl.Date,
                        "compliant": pl.Date,
                    },
                ),
                run_date=date(2026, 2, 25),
                prev_business_day=date(2026, 2, 24),
                output_root=root / "output",
                artifacts_root=root / "artifacts",
                logo_path=PROJECT_ROOT / "profile.example" / "logo.pdf",
                typst_bin="/bin/true",
                project_root=PROJECT_ROOT,
                no_compile=False,
                prune_history=False,
                keep_artifacts=True,
                secondary_labels={"ALPHA SCHOOL - 1001"},
                target_school_labels=["ALPHA SCHOOL - 1001"],
                reference=self._reference_with_closed_suspension_window(),
            )

            self.assertEqual(len(outputs), 1)
            self.assertEqual(outputs[0].terminal_status, "suspension_period_complete")
            self.assertTrue(
                outputs[0].pdf_path.name.endswith(
                    "_ALPHA_SCHOOL_1001_ISPA_SUSPENSION_PERIOD_COMPLETE.pdf"
                )
            )

    def test_school_year_boundary_can_be_overridden(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            outputs = write_reports(
                report_type="overdue",
                df=pl.DataFrame(
                    schema={
                        "school_label": pl.Utf8,
                        "last_name": pl.Utf8,
                        "first_name": pl.Utf8,
                        "date_of_birth": pl.Utf8,
                    }
                ),
                run_date=date(2026, 2, 25),
                prev_business_day=None,
                output_root=root / "output",
                artifacts_root=root / "artifacts",
                logo_path=PROJECT_ROOT / "profile.example" / "logo.pdf",
                typst_bin="/bin/true",
                project_root=PROJECT_ROOT,
                no_compile=False,
                prune_history=False,
                keep_artifacts=True,
                secondary_labels=set(),
                target_school_labels=["ALPHA SCHOOL - 1001"],
                school_year_start_month=1,
            )
            self.assertEqual(len(outputs), 1)
            self.assertTrue(outputs[0].pdf_path.name.startswith("2026_2027_"))

    def test_suspension_honors_report_rescinded_flag_with_inclusive_window(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            outputs = write_reports(
                report_type="suspension",
                df=pl.DataFrame(
                    {
                        "school_label": [
                            "ALPHA SCHOOL - 1001",
                            "ALPHA SCHOOL - 1001",
                        ],
                        "last_name": ["DOE", "SMITH"],
                        "first_name": ["JANE", "JOHN"],
                        "date_of_birth": [date(2010, 1, 1), date(2011, 1, 1)],
                        "compliant": [date(2026, 2, 24), date(2026, 2, 25)],
                        "report_rescinded": [False, True],
                    }
                ),
                run_date=date(2026, 2, 25),
                prev_business_day=date(2026, 2, 24),
                output_root=root / "output",
                artifacts_root=root / "artifacts",
                logo_path=PROJECT_ROOT / "profile.example" / "logo.pdf",
                typst_bin="/bin/true",
                project_root=PROJECT_ROOT,
                no_compile=False,
                prune_history=False,
                keep_artifacts=True,
                secondary_labels=set(),
                target_school_labels=["ALPHA SCHOOL - 1001"],
            )
            self.assertEqual(len(outputs), 1)
            self.assertEqual(outputs[0].counts["rescinded"], 1)


if __name__ == "__main__":
    unittest.main()
