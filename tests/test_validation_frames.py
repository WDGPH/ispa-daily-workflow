from __future__ import annotations

import sys
import unittest
from pathlib import Path

import polars as pl

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_ROOT))

from ispa_daily_workflow.validation.frames import (
    collect_school_labels,
    ensure_school_label_column,
    filter_by_school_ids,
)


class TestValidationFrames(unittest.TestCase):
    def test_ensure_school_label_column(self) -> None:
        frame = pl.DataFrame(
            {
                "school_name": ["ALPHA SCHOOL", "BETA SCHOOL"],
                "school_id": ["1001", "1002"],
            }
        )
        labeled = ensure_school_label_column(frame)
        self.assertEqual(
            labeled.get_column("school_label").to_list(),
            ["ALPHA SCHOOL - 1001", "BETA SCHOOL - 1002"],
        )

    def test_collect_school_labels_sorted_unique(self) -> None:
        frame = pl.DataFrame(
            {
                "school_label": [
                    "BETA SCHOOL - 1002",
                    "ALPHA SCHOOL - 1001",
                    "ALPHA SCHOOL - 1001",
                ]
            }
        )
        self.assertEqual(
            collect_school_labels(frame),
            ["ALPHA SCHOOL - 1001", "BETA SCHOOL - 1002"],
        )

    def test_filter_by_school_ids(self) -> None:
        frame = pl.DataFrame(
            {
                "client_id": ["c1", "c2", "c3"],
                "school_id": ["1001.0", "School 1002", "3000"],
            }
        )
        filtered = filter_by_school_ids(frame, school_ids={"1001", "1002"})
        self.assertEqual(filtered.height, 2)
        self.assertEqual(filtered.get_column("client_id").to_list(), ["c1", "c2"])

    def test_filter_by_school_ids_missing_column_returns_empty(self) -> None:
        frame = pl.DataFrame({"client_id": ["c1"]})
        filtered = filter_by_school_ids(frame, school_ids={"1001"})
        self.assertTrue(filtered.is_empty())


if __name__ == "__main__":
    unittest.main()
