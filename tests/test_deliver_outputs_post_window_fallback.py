from __future__ import annotations

import sys
import unittest
from datetime import date
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_ROOT))

from panorama_compliance.domain.delivery.pear_state import (  # noqa: E402
    empty_pear_report_frames_for_scope,
    scope_is_after_suspension_window,
)
from panorama_compliance.domain.delivery.routing import parse_scope_selection  # noqa: E402
from panorama_compliance.reference import SchoolRecord, SchoolReference  # noqa: E402


def _reference() -> SchoolReference:
    secondary = SchoolRecord(
        school_name="BETA SECONDARY SCHOOL",
        school_id="3001",
        level="SECONDARY",
        wave="SECONDARY1",
        fq_group="G2",
        suspension_applied_date=date(2026, 2, 1),
        suspension_window_start=date(2026, 2, 10),
        suspension_window_end=date(2026, 3, 10),
    )
    elementary = SchoolRecord(
        school_name="ALPHA ELEMENTARY SCHOOL",
        school_id="1001",
        level="ELEMENTARY",
        wave="ELEMENTARY2",
        fq_group="G1",
        suspension_applied_date=date(2026, 3, 1),
        suspension_window_start=date(2026, 3, 25),
        suspension_window_end=date(2026, 4, 21),
    )
    return SchoolReference(
        by_id={"3001": secondary, "1001": elementary},
        by_name={
            "BETA SECONDARY SCHOOL": secondary,
            "ALPHA ELEMENTARY SCHOOL": elementary,
        },
        secondary_labels={"BETA SECONDARY SCHOOL - 3001"},
    )


class TestDeliverOutputsPostWindowFallback(unittest.TestCase):
    def test_scope_is_after_suspension_window_for_secondary_wave(self) -> None:
        scope = parse_scope_selection(wave="SECONDARY1", level=None, school=None)
        self.assertTrue(
            scope_is_after_suspension_window(
                scope=scope,
                reference=_reference(),
                run_day=date(2026, 3, 11),
            )
        )

    def test_scope_is_not_after_suspension_window_for_elementary_wave(self) -> None:
        scope = parse_scope_selection(wave="ELEMENTARY2", level=None, school=None)
        self.assertFalse(
            scope_is_after_suspension_window(
                scope=scope,
                reference=_reference(),
                run_day=date(2026, 3, 11),
            )
        )

    def test_empty_suspension_fallback_uses_expected_slice(self) -> None:
        scope = parse_scope_selection(wave="SECONDARY1", level=None, school=None)
        frames = empty_pear_report_frames_for_scope(
            scope=scope,
            reference=_reference(),
            report_type="suspension",
        )
        self.assertEqual(set(frames.keys()), {"secondary1"})
        frame = frames["secondary1"]
        self.assertEqual(
            frame.columns,
            [
                "client_id",
                "school_id",
                "school_name",
                "school_label",
                "first_name",
                "last_name",
                "date_of_birth",
                "rescind_date",
            ],
        )
        self.assertEqual(frame.height, 0)


if __name__ == "__main__":
    unittest.main()
