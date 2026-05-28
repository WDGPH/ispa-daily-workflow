from __future__ import annotations

import sys
import unittest
from datetime import date
from pathlib import Path

import polars as pl

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_ROOT))

from ispa_daily_workflow.domain.delivery.rescind_reporting import (
    mark_unreported_rescinds_for_suspension_report,
    rescind_reporting_diagnostics,
)


class TestDeliverOutputsRescindFilter(unittest.TestCase):
    def test_marks_only_prior_active_to_rescinded_transitions(self) -> None:
        current = pl.DataFrame(
            {
                "client_id": ["0000000001", "0000000002", "0000000003", "0000000004"],
                "compliant": [
                    date(2026, 2, 25),
                    date(2026, 2, 25),
                    None,
                    date(2026, 2, 24),
                ],
            }
        )
        previous_authoritative = pl.DataFrame(
            {
                "client_id": ["0000000001", "0000000002", "0000000003"],
                "rescind_date": [None, date(2026, 2, 24), None],
            }
        )
        marked, unreported_count = mark_unreported_rescinds_for_suspension_report(
            current_frame=current,
            previous_authoritative_frame=previous_authoritative,
            run_day=date(2026, 2, 25),
            prev_business_day=date(2026, 2, 24),
        )

        self.assertEqual(unreported_count, 1)
        self.assertEqual(
            marked.sort("client_id").select("report_rescinded").to_series().to_list(),
            [True, False, False, False],
        )

    def test_rescind_diagnostics_tracks_date_shift_without_transition(self) -> None:
        current = pl.DataFrame(
            {
                "client_id": ["0000000001", "0000000002", "0000000003"],
                "compliant": [date(2026, 2, 25), date(2026, 2, 25), None],
            }
        )
        previous_authoritative = pl.DataFrame(
            {
                "client_id": ["0000000001", "0000000002", "0000000003"],
                "rescind_date": [None, date(2026, 2, 24), None],
            }
        )
        diagnostics = rescind_reporting_diagnostics(
            current_frame=current,
            previous_authoritative_frame=previous_authoritative,
            run_day=date(2026, 2, 25),
            prev_business_day=date(2026, 2, 24),
        )
        self.assertEqual(diagnostics["rescinds_transition_count"], 1)
        self.assertEqual(diagnostics["rescinds_date_shift_only_count"], 1)
        self.assertEqual(diagnostics["prior_active_count"], 2)
        self.assertEqual(diagnostics["current_active_count"], 1)


if __name__ == "__main__":
    unittest.main()
