from __future__ import annotations

import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_ROOT))

from ispa_daily_workflow.pipeline.deliver_outputs import (
    _pdf_school_status_counts,
)


class TestDeliverOutputsPdfStatus(unittest.TestCase):
    def test_counts_final_and_list_school_status(self) -> None:
        paths = [
            Path("2025_2026_ALPHA_1001_ISPA_FINAL_SUMMARY.pdf"),
            Path("2025_2026_CHARLIE_1003_ISPA_SUSPENSION_PERIOD_COMPLETE.pdf"),
            Path("20260225_BRAVO_1002_OVERDUE_LIST.pdf"),
            Path("20260225_DELTA_1004_SUSPENSION_LIST.pdf"),
            Path("2026_2027_ECHO_1005_ISPA_FINAL_SUMMARY.pdf"),
        ]
        final_count, list_count = _pdf_school_status_counts(paths)
        self.assertEqual(final_count, 3)
        self.assertEqual(list_count, 2)


if __name__ == "__main__":
    unittest.main()
