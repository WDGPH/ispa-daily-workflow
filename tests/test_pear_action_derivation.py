from __future__ import annotations

import sys
import unittest
from datetime import date
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_ROOT))

from ispa_daily_workflow.domain.pear.intake import (
    WaveWindow,
    _derive_action,
)


class TestPearActionDerivation(unittest.TestCase):
    def setUp(self) -> None:
        self.window = WaveWindow(
            applied_date=date(2026, 2, 9),
            suspension_window_start=date(2026, 2, 25),
            suspension_window_end=date(2026, 3, 24),
        )

    def test_before_applied_date_is_no_action(self) -> None:
        action, action_date = _derive_action(
            report_date=date(2026, 2, 8),
            wave_window=self.window,
        )
        self.assertEqual(action, "no_action")
        self.assertIsNone(action_date)

    def test_pre_suspension_period_before_final_day_is_delete(self) -> None:
        action, action_date = _derive_action(
            report_date=date(2026, 2, 20),
            wave_window=self.window,
        )
        self.assertEqual(action, "delete")
        self.assertEqual(action_date, date(2026, 2, 20))

    def test_single_day_before_suspension_is_future_dated_rescind(self) -> None:
        action, action_date = _derive_action(
            report_date=date(2026, 2, 24),
            wave_window=self.window,
        )
        self.assertEqual(action, "rescind")
        self.assertEqual(action_date, date(2026, 2, 25))

    def test_suspension_window_uses_same_day_rescind(self) -> None:
        action, action_date = _derive_action(
            report_date=date(2026, 2, 25),
            wave_window=self.window,
        )
        self.assertEqual(action, "rescind")
        self.assertEqual(action_date, date(2026, 2, 25))

    def test_after_suspension_window_is_no_action(self) -> None:
        action, action_date = _derive_action(
            report_date=date(2026, 3, 25),
            wave_window=self.window,
        )
        self.assertEqual(action, "no_action")
        self.assertIsNone(action_date)


if __name__ == "__main__":
    unittest.main()
