from __future__ import annotations

import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_ROOT))

from ispa_daily_workflow.schema import ValidationError
from ispa_daily_workflow.validation.catalog import (
    RULE_PEAR_DELETE_ACTION_MATCH_ID,
    RULE_PEAR_DISAPPEARANCE_REHYDRATION_ID,
    RULE_PEAR_SUSPENSION_CONTINUITY_ID,
    RULE_PEAR_WAVE_WINDOW_AUTHORITY_ID,
)
from ispa_daily_workflow.validation.pear import (
    continuity_warning_results,
    delete_action_match_warning,
    disappearance_warning_results,
    require_wave_window_authority,
)
from tests.reference_factories import alpha_school_reference


class TestValidationPear(unittest.TestCase):
    def test_require_wave_window_authority(self) -> None:
        windows = require_wave_window_authority(
            reference=alpha_school_reference(with_wave_windows=True),
            context="test-context",
        )
        self.assertIn("ELEMENTARY1", windows)

    def test_require_wave_window_authority_fails_without_windows(self) -> None:
        with self.assertRaisesRegex(
            ValidationError, RULE_PEAR_WAVE_WINDOW_AUTHORITY_ID
        ):
            require_wave_window_authority(
                reference=alpha_school_reference(with_wave_windows=False),
                context="test-context",
            )

    def test_delete_action_match_warning(self) -> None:
        warning = delete_action_match_warning(
            client_ids=["1000000001", "1000000001", "1000000002"]
        )
        self.assertIsNotNone(warning)
        assert warning is not None
        self.assertEqual(warning.rule_id, RULE_PEAR_DELETE_ACTION_MATCH_ID)
        self.assertEqual(warning.count, 2)
        self.assertIn("client_id=1000000001 action_required=delete", warning.message)

    def test_delete_action_match_warning_none_when_no_ids(self) -> None:
        self.assertIsNone(delete_action_match_warning(client_ids=[]))

    def test_continuity_warning_results(self) -> None:
        results = continuity_warning_results(
            ("continuity warning one", "continuity warning two")
        )
        self.assertEqual(len(results), 2)
        self.assertTrue(
            all(
                result.rule_id == RULE_PEAR_SUSPENSION_CONTINUITY_ID
                for result in results
            )
        )

    def test_disappearance_warning_results(self) -> None:
        results = disappearance_warning_results(("rehydrated row warning",))
        self.assertEqual(len(results), 1)
        self.assertEqual(
            results[0].rule_id,
            RULE_PEAR_DISAPPEARANCE_REHYDRATION_ID,
        )


if __name__ == "__main__":
    unittest.main()
