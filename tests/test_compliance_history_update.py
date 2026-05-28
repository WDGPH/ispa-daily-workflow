from __future__ import annotations

import sys
import unittest
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory

import polars as pl

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_ROOT))

from ispa_daily_workflow.compliance_history import (
    update_compliance_history,
)
from ispa_daily_workflow.schema import load_schema, schema_field_names


class TestComplianceHistoryUpdate(unittest.TestCase):
    def test_refreshes_source_file_for_existing_active_client(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            compliance_history_dir = root / "compliance_history"
            compliance_history_dir.mkdir(parents=True, exist_ok=True)

            prior_path = (
                compliance_history_dir
                / "20260213_panorama_secondary1_compliance_history.parquet"
            )
            current_path = root / "20260217_panorama_secondary1_noncompliant.parquet"

            schema = load_schema(
                PROJECT_ROOT / "schema",
                "processed_panorama_suspension_compliance_history_v2.0.json",
            )
            columns = list(schema_field_names(schema))
            prior_row = {column: None for column in columns}
            prior_row.update(
                {
                    "client_id": "0000000001",
                    "school_id": "000001",
                    "school_name": "SYNTHETIC SECONDARY SCHOOL",
                    "first_name": "TEST",
                    "last_name": "STUDENT",
                    "date_of_birth": date(2010, 1, 1),
                    "source_file": (
                        "20260128_panorama_compliance_secondary_000001_2009_and_earlier.xlsx"
                    ),
                    "compliant": None,
                }
            )
            prior = pl.DataFrame([prior_row]).select(columns)
            prior.write_parquet(prior_path)

            noncompliant_schema = load_schema(
                PROJECT_ROOT / "schema",
                "processed_panorama_noncompliant_v1.0.json",
            )
            noncompliant_columns = list(schema_field_names(noncompliant_schema))
            current_row = {column: None for column in noncompliant_columns}
            current_row.update(
                {
                    "client_id": "0000000001",
                    "school_id": "000001",
                    "school_name": "SYNTHETIC SECONDARY SCHOOL",
                    "first_name": "TEST",
                    "last_name": "STUDENT",
                    "date_of_birth": date(2010, 1, 1),
                    "source_file": (
                        "20260217_panorama_compliance_secondary_000001_2009_and_earlier.xlsx"
                    ),
                }
            )
            current = pl.DataFrame([current_row]).select(noncompliant_columns)
            current.write_parquet(current_path)

            written = update_compliance_history(
                run_date="20260217",
                current_combined_path=current_path,
                compliance_history_dir=compliance_history_dir,
                schema_root=PROJECT_ROOT / "schema",
            )

            self.assertEqual(len(written), 1)
            output = pl.read_parquet(written[0])
            refreshed = output.filter(pl.col("client_id") == "0000000001")
            self.assertEqual(refreshed.height, 1)
            self.assertEqual(
                refreshed.get_column("source_file").to_list(),
                ["20260217_panorama_compliance_secondary_000001_2009_and_earlier.xlsx"],
            )


if __name__ == "__main__":
    unittest.main()
