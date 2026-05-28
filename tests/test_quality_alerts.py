from __future__ import annotations

import sys
import unittest
from pathlib import Path

import polars as pl

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_ROOT))

from panorama_compliance.quality.alerts import build_alerts  # noqa: E402


class TestQualityAlerts(unittest.TestCase):
    def test_previous_only_school_keeps_school_label(self) -> None:
        current_df = pl.DataFrame({"school_label": ["SCHOOL A"], "client_id": ["1"]})
        previous_df = pl.DataFrame({"school_label": ["SCHOOL B"], "client_id": ["2"]})

        alerts = build_alerts(
            current_df=current_df,
            previous_df=previous_df,
            expected_input_count=None,
            observed_input_count=0,
            percent_change_threshold=0.25,
        )

        school_delta_alerts = [
            alert for alert in alerts if alert.code == "school_row_delta"
        ]
        self.assertEqual(len(school_delta_alerts), 1)
        alert = school_delta_alerts[0]
        self.assertEqual(alert.context.get("school_label"), "SCHOOL B")
        self.assertEqual(
            alert.message,
            "School SCHOOL B changed by -100.00% (1 -> 0)",
        )
        self.assertNotIn("UNKNOWN", alert.message)


if __name__ == "__main__":
    unittest.main()
