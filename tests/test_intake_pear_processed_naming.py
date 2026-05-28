from __future__ import annotations

import sys
import unittest
from datetime import date
from pathlib import Path

import polars as pl

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_ROOT))

from panorama_compliance.pipeline.intake_pear import (  # noqa: E402
    _partition_processed_frame_by_wave,
    _processed_wave_filename,
)
from panorama_compliance.domain.pear.intake import (  # noqa: E402
    REPORT_OVERDUE,
    REPORT_SUSPENSION,
)
from panorama_compliance.reference import SchoolRecord, SchoolReference  # noqa: E402


def _reference() -> SchoolReference:
    elementary = SchoolRecord(
        school_name="ALPHA ELEMENTARY SCHOOL",
        school_id="1001",
        level="ELEMENTARY",
        wave="ELEMENTARY1",
        fq_group="G1",
    )
    secondary = SchoolRecord(
        school_name="BETA SECONDARY SCHOOL",
        school_id="3001",
        level="SECONDARY",
        wave="SECONDARY1",
        fq_group="G2",
    )
    return SchoolReference(
        by_id={"1001": elementary, "3001": secondary},
        by_name={
            elementary.school_name: elementary,
            secondary.school_name: secondary,
        },
        secondary_labels={"BETA SECONDARY SCHOOL - 3001"},
    )


class TestIntakePearProcessedNaming(unittest.TestCase):
    def test_partitions_processed_frame_by_wave(self) -> None:
        frame = pl.DataFrame(
            [
                {
                    "client_id": "0000000001",
                    "school_id": "1001",
                    "school_name": "ALPHA ELEMENTARY SCHOOL",
                    "first_name": "A",
                    "last_name": "ONE",
                    "date_of_birth": date(2012, 1, 1),
                    "overdue_agents": "MMR",
                },
                {
                    "client_id": "0000000002",
                    "school_id": "3001",
                    "school_name": "BETA SECONDARY SCHOOL",
                    "first_name": "B",
                    "last_name": "TWO",
                    "date_of_birth": date(2011, 2, 2),
                    "overdue_agents": "TDAP",
                },
            ]
        )
        partitions = _partition_processed_frame_by_wave(
            frame=frame,
            report_type=REPORT_OVERDUE,
            canonical_filename="20260224_overdue_list_pear.xlsx",
            reference=_reference(),
            source_file=Path("source.xlsx"),
        )
        self.assertEqual(set(partitions.keys()), {"elementary1", "secondary1"})
        self.assertEqual(partitions["elementary1"].height, 1)
        self.assertEqual(partitions["secondary1"].height, 1)

    def test_empty_suspension_frame_uses_level_scoped_wave_tokens(self) -> None:
        empty_frame = pl.DataFrame(
            schema={
                "client_id": pl.Utf8,
                "school_id": pl.Utf8,
                "school_name": pl.Utf8,
                "first_name": pl.Utf8,
                "last_name": pl.Utf8,
                "date_of_birth": pl.Date,
                "rescind_date": pl.Date,
            }
        )
        partitions = _partition_processed_frame_by_wave(
            frame=empty_frame,
            report_type=REPORT_SUSPENSION,
            canonical_filename="20260224_suspension_list_elementary.xlsx",
            reference=_reference(),
            source_file=Path("source.xlsx"),
        )
        self.assertEqual(set(partitions.keys()), {"elementary1"})

    def test_processed_wave_filename_contract(self) -> None:
        name = _processed_wave_filename(
            report_date=date(2026, 2, 24),
            report_type=REPORT_OVERDUE,
            slice_token="secondary1",
        )
        self.assertEqual(name, "20260224_pear_overdue_list_secondary1.parquet")


if __name__ == "__main__":
    unittest.main()
