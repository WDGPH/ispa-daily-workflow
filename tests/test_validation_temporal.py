from __future__ import annotations

import sys
import unittest
from datetime import date
from pathlib import Path

import polars as pl

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_ROOT))

from panorama_compliance.schema import ValidationError  # noqa: E402
from panorama_compliance.validation.catalog import (  # noqa: E402
    RULE_PEAR_RESCIND_WINDOW_START_ID,
    RULE_PREVIOUS_BUSINESS_DAY_ID,
    RULE_PREVIOUS_SCOPE_DATA_ID,
    RULE_TEMPORAL_BOUNDS_ID,
)
from panorama_compliance.validation.temporal import (  # noqa: E402
    parse_date_token,
    previous_scope_data_file_warning,
    require_increasing_date_range,
    require_previous_business_day,
    validate_rescind_window_start_bound,
    validate_temporal_bounds,
)


class TestValidationTemporal(unittest.TestCase):
    def test_parse_date_token(self) -> None:
        parsed = parse_date_token("20260214", field_name="run_date")
        self.assertEqual(parsed, date(2026, 2, 14))
        with self.assertRaisesRegex(ValidationError, "YYYYMMDD"):
            parse_date_token("2026-02-14", field_name="run_date")

    def test_require_increasing_date_range(self) -> None:
        require_increasing_date_range(
            start_date=date(2026, 2, 13),
            end_date=date(2026, 2, 14),
            start_label="previous_date",
            end_label="run_date",
            context="daily diff",
        )
        with self.assertRaisesRegex(ValidationError, "invalid date range"):
            require_increasing_date_range(
                start_date=date(2026, 2, 14),
                end_date=date(2026, 2, 14),
                start_label="previous_date",
                end_label="run_date",
                context="daily diff",
            )

    def test_previous_scope_data_file_warning(self) -> None:
        no_warning = previous_scope_data_file_warning(
            previous_date="20260213",
            scope_label="wave=SECONDARY1",
            output_id="sharepoint.panorama.diff.xlsx",
            required_slices=["secondary1"],
            available_slices=["secondary1", "elementary1"],
        )
        self.assertIsNone(no_warning)
        warning = previous_scope_data_file_warning(
            previous_date="20260213",
            scope_label="wave=SECONDARY1",
            output_id="sharepoint.panorama.diff.xlsx",
            required_slices=["secondary1"],
            available_slices=["elementary1"],
        )
        self.assertIsNotNone(warning)
        assert warning is not None
        self.assertEqual(warning.rule_id, RULE_PREVIOUS_SCOPE_DATA_ID)
        self.assertEqual(warning.severity, "warning")
        self.assertIn("missing_slices=['secondary1']", warning.message)

    def test_previous_scope_data_file_warning_no_download_note(self) -> None:
        warning = previous_scope_data_file_warning(
            previous_date="20260213",
            scope_label="wave=SECONDARY1",
            output_id="sharepoint.suspension.pdf",
            required_slices=["secondary1"],
            available_slices=[],
            download_enabled=False,
        )
        self.assertIsNotNone(warning)
        assert warning is not None
        self.assertIn(
            "No-download mode checks only local compliance_history snapshots",
            warning.message,
        )

    def test_require_previous_business_day_raises(self) -> None:
        with self.assertRaisesRegex(ValidationError, RULE_PREVIOUS_BUSINESS_DAY_ID):
            require_previous_business_day(
                previous_business_day=None,
                run_date="20260214",
                label="sharepoint.suspension.pdf",
            )

    def test_temporal_bounds_fail_on_future_dob(self) -> None:
        frame = pl.DataFrame(
            {
                "client_id": ["1001"],
                "date_of_birth": [date(2026, 2, 15)],
                "compliant": [None],
            }
        )
        with self.assertRaisesRegex(ValidationError, "dob_after_run_day"):
            validate_temporal_bounds(
                frame=frame,
                run_day=date(2026, 2, 14),
                label="test_frame",
            )

    def test_temporal_bounds_warn_on_age_outside_policy(self) -> None:
        frame = pl.DataFrame(
            {
                "client_id": ["1001"],
                "date_of_birth": [date(2000, 1, 1)],
                "compliant": [None],
                "source_file": ["20260217_panorama_compliance_secondary_fq1.xlsx"],
            }
        )
        warnings = validate_temporal_bounds(
            frame=frame,
            run_day=date(2026, 2, 14),
            label="test_frame",
        )
        self.assertEqual(len(warnings), 1)
        self.assertEqual(warnings[0].rule_id, RULE_TEMPORAL_BOUNDS_ID)
        self.assertEqual(warnings[0].code, "age_out_of_policy")
        self.assertIn(
            "ISPA age policy warning in test_frame: 1 rows outside 4-17:",
            warnings[0].message,
        )
        self.assertIn(
            "    client_id=1001 source_file=20260217_panorama_compliance_secondary_fq1.xlsx",
            warnings[0].message,
        )
        self.assertEqual(warnings[0].context.get("client_ids"), ["1001"])
        self.assertEqual(
            warnings[0].context.get("source_files"),
            ["20260217_panorama_compliance_secondary_fq1.xlsx"],
        )
        self.assertEqual(
            warnings[0].context.get("client_id_to_source_file"),
            [
                {
                    "client_id": "1001",
                    "source_file": "20260217_panorama_compliance_secondary_fq1.xlsx",
                }
            ],
        )

    def test_temporal_bounds_skips_age_warning_for_compliant_rows(self) -> None:
        frame = pl.DataFrame(
            {
                "client_id": ["1001"],
                "date_of_birth": [date(2000, 1, 1)],
                "compliant": [date(2026, 2, 13)],
                "source_file": ["20260217_panorama_compliance_secondary_fq1.xlsx"],
            }
        )
        warnings = validate_temporal_bounds(
            frame=frame,
            run_day=date(2026, 2, 14),
            label="test_frame",
        )
        self.assertEqual(warnings, [])

    def test_validate_rescind_window_start_bound_passes_when_in_window(self) -> None:
        frame = pl.DataFrame(
            {
                "client_id": ["1001"],
                "wave": ["ELEMENTARY1"],
                "rescind_date": [date(2026, 2, 25)],
            }
        )
        validate_rescind_window_start_bound(
            frame=frame,
            wave_window_starts={"ELEMENTARY1": date(2026, 2, 25)},
            label="suspension_active",
        )

    def test_validate_rescind_window_start_bound_fails_before_window_start(
        self,
    ) -> None:
        frame = pl.DataFrame(
            {
                "client_id": ["1001"],
                "wave": ["ELEMENTARY1"],
                "rescind_date": [date(2026, 2, 24)],
            }
        )
        with self.assertRaisesRegex(
            ValidationError,
            RULE_PEAR_RESCIND_WINDOW_START_ID,
        ):
            validate_rescind_window_start_bound(
                frame=frame,
                wave_window_starts={"ELEMENTARY1": date(2026, 2, 25)},
                label="suspension_active",
            )


if __name__ == "__main__":
    unittest.main()
