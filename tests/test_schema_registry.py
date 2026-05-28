from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

import polars as pl

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_ROOT))

from panorama_compliance.schema import (  # noqa: E402
    ValidationError,
    dataset_field_names,
    load_dataset_registry,
    project_to_dataset,
    resolve_dataset_schema,
)


class TestSchemaRegistry(unittest.TestCase):
    def test_load_registry_contains_core_dataset_ids(self) -> None:
        registry = load_dataset_registry(PROJECT_ROOT / "schema")
        self.assertEqual(registry.version, "1.0")
        self.assertIn("processed.panorama.noncompliant", registry.datasets)
        self.assertIn("delivery.sharepoint.diff", registry.datasets)

    def test_unknown_dataset_id_fails(self) -> None:
        with self.assertRaises(ValidationError):
            resolve_dataset_schema(
                "missing.dataset.id",
                schema_root=PROJECT_ROOT / "schema",
            )

    def test_project_to_dataset_enforces_schema_column_order(self) -> None:
        with tempfile.TemporaryDirectory():
            schema_root = PROJECT_ROOT / "schema"
            columns = dataset_field_names(
                "delivery.sharepoint.diff",
                schema_root=schema_root,
            )
            frame = pl.DataFrame(
                {
                    "client_id": ["0000000001"],
                    "school_id": ["1001"],
                }
            )
            projected = project_to_dataset(
                frame,
                "delivery.sharepoint.diff",
                schema_root=schema_root,
            )
            self.assertEqual(projected.columns, list(columns))
            self.assertEqual(projected.height, 1)


if __name__ == "__main__":
    unittest.main()
