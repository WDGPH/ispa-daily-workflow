from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_ROOT))

from panorama_compliance.compliance_history import (  # noqa: E402
    discover_compliance_history_by_slice_for_date,
)


class TestComplianceHistoryDiscovery(unittest.TestCase):
    def test_discover_compliance_history_by_slice_for_date(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "20260213_panorama_secondary1_compliance_history.parquet").touch()
            (root / "20260213_panorama_elementary1_compliance_history.parquet").touch()
            (root / "20260214_panorama_secondary1_compliance_history.parquet").touch()

            discovered = discover_compliance_history_by_slice_for_date(
                root,
                run_date="20260213",
            )
            self.assertEqual(
                set(discovered),
                {"secondary1", "elementary1"},
            )
            self.assertTrue(
                str(discovered["secondary1"]).endswith(
                    "20260213_panorama_secondary1_compliance_history.parquet"
                )
            )


if __name__ == "__main__":
    unittest.main()
