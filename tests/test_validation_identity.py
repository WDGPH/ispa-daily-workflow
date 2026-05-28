from __future__ import annotations

import sys
import unittest
from pathlib import Path

import polars as pl

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_ROOT))

from panorama_compliance.schema import ValidationError  # noqa: E402
from panorama_compliance.validation.identity import (  # noqa: E402
    ensure_additions_allowed,
    ensure_subset,
    ensure_unique_identifier,
    normalize_key_column,
    sample_key_values,
    subset_difference,
)


class TestValidationIdentity(unittest.TestCase):
    def test_normalize_key_column(self) -> None:
        frame = pl.DataFrame({"client_id": ["1001.0", " 1002 "]})
        normalized = normalize_key_column(frame, key="client_id", label="test")
        self.assertEqual(normalized.get_column("client_id").to_list(), ["1001", "1002"])

    def test_ensure_unique_identifier_raises(self) -> None:
        frame = pl.DataFrame({"client_id": ["1", "1"]})
        with self.assertRaisesRegex(ValidationError, "duplicate values in client_id"):
            ensure_unique_identifier(frame, key="client_id", label="dup_test")

    def test_subset_difference_and_ensure_subset(self) -> None:
        current = pl.DataFrame({"client_id": ["1", "2", "3"]})
        previous = pl.DataFrame({"client_id": ["1", "2"]})
        outside = subset_difference(
            current,
            previous,
            key="client_id",
            subset_label="current",
            superset_label="previous",
        )
        self.assertEqual(outside.get_column("client_id").to_list(), ["3"])

        with self.assertRaisesRegex(
            ValidationError, "contains 1 client_id values not in"
        ):
            ensure_subset(
                current,
                previous,
                key="client_id",
                subset_label="current",
                superset_label="previous",
                error_prefix="subset failure",
            )

    def test_additions_policy(self) -> None:
        additions = pl.DataFrame({"client_id": ["10", "11"]})
        with self.assertRaises(ValidationError) as exc:
            ensure_additions_allowed(
                additions,
                key="client_id",
                allow_additions=False,
                label="history merge",
            )
        message = str(exc.exception)
        self.assertIn("unexpected client_id additions", message)
        self.assertIn("affected_client_ids=['10', '11']", message)
        self.assertNotIn("sample_client_id", message)

        additions_with_source = pl.DataFrame(
            {
                "client_id": ["10", "11"],
                "source_file": ["a.xlsx", "b.xlsx"],
            }
        )
        with self.assertRaises(ValidationError) as exc_with_source:
            ensure_additions_allowed(
                additions_with_source,
                key="client_id",
                allow_additions=False,
                label="history merge",
                source_column="source_file",
            )
        source_message = str(exc_with_source.exception)
        self.assertIn("source_files=['a.xlsx', 'b.xlsx']", source_message)
        self.assertIn(
            "client_id_to_source_file=[{'client_id': '10', 'source_file': 'a.xlsx'}, {'client_id': '11', 'source_file': 'b.xlsx'}]",
            source_message,
        )

        # no raise when allowed
        ensure_additions_allowed(
            additions,
            key="client_id",
            allow_additions=True,
            label="history merge",
        )

    def test_sample_key_values(self) -> None:
        frame = pl.DataFrame({"client_id": ["1", "2"]})
        self.assertEqual(sample_key_values(frame, key="client_id"), ["1", "2"])


if __name__ == "__main__":
    unittest.main()
