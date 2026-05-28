from __future__ import annotations

import sys
import unittest
from pathlib import Path

import polars as pl

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_ROOT))

from panorama_compliance.schema import ValidationError  # noqa: E402
from panorama_compliance.validation.contracts import (  # noqa: E402
    project_delivery_contract,
    validate_report_delivery_contract,
)


class TestValidationContracts(unittest.TestCase):
    def test_project_delivery_contract_for_diff(self) -> None:
        frame = pl.DataFrame(
            {
                "client_id": ["1"],
                "school_id": ["1001"],
                "school_name": ["ALPHA"],
                "first_name": ["A"],
                "last_name": ["B"],
                "date_of_birth": ["2012-01-01"],
                "extra": ["ignore"],
            }
        )
        projected = project_delivery_contract(
            frame,
            output_id="sharepoint.panorama.diff.xlsx",
            schema_root=PROJECT_ROOT / "schema",
        )
        self.assertEqual(
            projected.columns,
            [
                "client_id",
                "school_id",
                "school_name",
                "first_name",
                "middle_name",
                "last_name",
                "date_of_birth",
            ],
        )
        self.assertEqual(projected.height, 1)

    def test_project_delivery_contract_for_action_queue(self) -> None:
        frame = pl.DataFrame(
            {
                "client_id": ["1"],
                "school_id": ["1001"],
                "school_name": ["ALPHA"],
                "first_name": ["A"],
                "last_name": ["B"],
                "date_of_birth": ["2012-01-01"],
                "action_required": ["rescind"],
                "action_date": ["2026-02-24"],
            }
        )
        projected = project_delivery_contract(
            frame,
            output_id="sharepoint.action_queue.xlsx",
            schema_root=PROJECT_ROOT / "schema",
        )
        self.assertEqual(
            projected.columns,
            [
                "client_id",
                "school_id",
                "school_name",
                "first_name",
                "last_name",
                "date_of_birth",
                "action_required",
                "action_date",
            ],
        )
        self.assertEqual(projected.height, 1)

    def test_validate_report_delivery_contract_raises_when_missing_columns(
        self,
    ) -> None:
        frame = pl.DataFrame({"school_label": ["ALPHA - 1001"]})
        with self.assertRaisesRegex(ValidationError, "missing required columns"):
            validate_report_delivery_contract(
                frame,
                output_id="sharepoint.suspension.pdf",
            )


if __name__ == "__main__":
    unittest.main()
