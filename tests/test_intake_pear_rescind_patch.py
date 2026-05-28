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

from panorama_compliance.pipeline.intake_pear import (  # noqa: E402
    _ProcessedFile,
    _patch_processed_suspension_rescinds,
)
from panorama_compliance.domain.pear.intake import (  # noqa: E402
    REPORT_SUSPENSION,
    REPORT_SUSPENSION_VS_OVERDUE,
)


class TestIntakePearRescindPatch(unittest.TestCase):
    def test_patches_matching_rescinds_without_adding_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            suspension_path = tmp_path / "20260224_suspension_list_elementary.parquet"
            action_path = tmp_path / "20260224_suspension_vs_overdue.parquet"

            pl.DataFrame(
                [
                    {
                        "client_id": "0000000001",
                        "school_id": "1001",
                        "school_name": "ALPHA ELEMENTARY SCHOOL",
                        "first_name": "A",
                        "last_name": "One",
                        "date_of_birth": date(2012, 1, 1),
                        "rescind_date": None,
                    },
                    {
                        "client_id": "0000000002",
                        "school_id": "1001",
                        "school_name": "ALPHA ELEMENTARY SCHOOL",
                        "first_name": "B",
                        "last_name": "Two",
                        "date_of_birth": date(2012, 2, 2),
                        "rescind_date": date(2026, 2, 20),
                    },
                ]
            ).write_parquet(suspension_path)

            pl.DataFrame(
                [
                    {
                        "client_id": "0000000001",
                        "school_id": "1001",
                        "school_name": "ALPHA ELEMENTARY SCHOOL",
                        "first_name": "A",
                        "last_name": "One",
                        "date_of_birth": date(2012, 1, 1),
                        "action_required": "rescind",
                        "action_date": date(2026, 2, 25),
                    },
                    {
                        "client_id": "0000000003",
                        "school_id": "1001",
                        "school_name": "ALPHA ELEMENTARY SCHOOL",
                        "first_name": "C",
                        "last_name": "Three",
                        "date_of_birth": date(2012, 3, 3),
                        "action_required": "rescind",
                        "action_date": date(2026, 2, 25),
                    },
                    {
                        "client_id": "0000000002",
                        "school_id": "1001",
                        "school_name": "ALPHA ELEMENTARY SCHOOL",
                        "first_name": "B",
                        "last_name": "Two",
                        "date_of_birth": date(2012, 2, 2),
                        "action_required": "delete",
                        "action_date": date(2026, 2, 24),
                    },
                ]
            ).write_parquet(action_path)

            processed_files = [
                _ProcessedFile(
                    source_file=suspension_path,
                    report_type=REPORT_SUSPENSION,
                    report_date=date(2026, 2, 24),
                    landing_output=None,
                    processed_output=suspension_path,
                    landing_rows=0,
                    processed_rows=2,
                    no_action_rows=0,
                    warning_count=0,
                    warnings=(),
                ),
                _ProcessedFile(
                    source_file=action_path,
                    report_type=REPORT_SUSPENSION_VS_OVERDUE,
                    report_date=date(2026, 2, 24),
                    landing_output=None,
                    processed_output=action_path,
                    landing_rows=0,
                    processed_rows=3,
                    no_action_rows=0,
                    warning_count=0,
                    warnings=(),
                ),
            ]

            summary = _patch_processed_suspension_rescinds(
                processed_files=processed_files
            )

            patched = pl.read_parquet(suspension_path).sort("client_id")
            self.assertEqual(patched.height, 2)
            self.assertEqual(
                patched.get_column("client_id").to_list(),
                ["0000000001", "0000000002"],
            )
            self.assertEqual(
                patched.filter(pl.col("client_id") == "0000000001").get_column(
                    "rescind_date"
                )[0],
                date(2026, 2, 25),
            )
            self.assertEqual(
                patched.filter(pl.col("client_id") == "0000000002").get_column(
                    "rescind_date"
                )[0],
                date(2026, 2, 20),
            )
            self.assertEqual(summary["rescind_action_rows"], 2)
            self.assertEqual(summary["matched_rows"], 1)
            self.assertEqual(summary["patched_rows"], 1)
            self.assertEqual(summary["unmatched_action_rows"], 1)
            self.assertEqual(summary["delete_action_rows"], 1)
            self.assertEqual(summary["matched_delete_rows"], 1)
            self.assertEqual(summary["unmatched_delete_action_rows"], 0)
            self.assertEqual(summary["patched_files"], 1)

    def test_handles_empty_action_frame_with_null_join_key_dtype(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            suspension_path = tmp_path / "20260224_suspension_list_elementary.parquet"
            action_path = tmp_path / "20260224_suspension_vs_overdue.parquet"

            pl.DataFrame(
                [
                    {
                        "client_id": "0000000001",
                        "school_id": "1001",
                        "school_name": "ALPHA ELEMENTARY SCHOOL",
                        "first_name": "A",
                        "last_name": "One",
                        "date_of_birth": date(2012, 1, 1),
                        "rescind_date": None,
                    },
                ]
            ).write_parquet(suspension_path)

            # Mirrors the historical failure mode where an empty action frame
            # was written with Null dtypes for all columns.
            pl.DataFrame(
                [],
                schema=[
                    "client_id",
                    "school_id",
                    "school_name",
                    "first_name",
                    "last_name",
                    "date_of_birth",
                    "action_required",
                    "action_date",
                ],
                orient="row",
            ).write_parquet(action_path)

            processed_files = [
                _ProcessedFile(
                    source_file=suspension_path,
                    report_type=REPORT_SUSPENSION,
                    report_date=date(2026, 2, 24),
                    landing_output=None,
                    processed_output=suspension_path,
                    landing_rows=0,
                    processed_rows=1,
                    no_action_rows=0,
                    warning_count=0,
                    warnings=(),
                ),
                _ProcessedFile(
                    source_file=action_path,
                    report_type=REPORT_SUSPENSION_VS_OVERDUE,
                    report_date=date(2026, 2, 24),
                    landing_output=None,
                    processed_output=action_path,
                    landing_rows=0,
                    processed_rows=0,
                    no_action_rows=0,
                    warning_count=0,
                    warnings=(),
                ),
            ]

            summary = _patch_processed_suspension_rescinds(
                processed_files=processed_files
            )

            patched = pl.read_parquet(suspension_path)
            self.assertEqual(patched.height, 1)
            self.assertEqual(summary["rescind_action_rows"], 0)
            self.assertEqual(summary["matched_rows"], 0)
            self.assertEqual(summary["patched_rows"], 0)
            self.assertEqual(summary["delete_action_rows"], 0)
            self.assertEqual(summary["matched_delete_rows"], 0)
            self.assertEqual(summary["patched_files"], 0)


if __name__ == "__main__":
    unittest.main()
