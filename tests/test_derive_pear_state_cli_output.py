from __future__ import annotations

import sys
import unittest
from pathlib import Path

import polars as pl

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_ROOT))

from ispa_daily_workflow.pipeline.derive_pear_state import (
    _disappearance_client_ids_text,
)


class TestDerivePearStateCliOutput(unittest.TestCase):
    def test_disappearance_client_ids_hidden_when_not_verbose(self) -> None:
        evidence = pl.DataFrame({"client_id": ["1000000001", "1000000002"]})
        output = _disappearance_client_ids_text(
            disappearance_evidence=evidence,
            verbose=False,
        )
        self.assertIsNone(output)

    def test_disappearance_client_ids_rendered_when_verbose(self) -> None:
        evidence = pl.DataFrame({"client_id": ["1000000001", "1000000002"]})
        output = _disappearance_client_ids_text(
            disappearance_evidence=evidence,
            verbose=True,
        )
        self.assertEqual(output, "  disappearance_client_ids=1000000001, 1000000002")


if __name__ == "__main__":
    unittest.main()
