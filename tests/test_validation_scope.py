from __future__ import annotations

import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_ROOT))

from panorama_compliance.validation.scope import (  # noqa: E402
    ALL_SCOPE_TOKEN,
    normalize_level_filter_values,
    normalize_level_scope_value,
    parse_scope_selection,
    normalize_school_id_filter_values,
    normalize_school_scope_value,
    normalize_wave_filter_values,
    normalize_wave_scope_value,
)


class TestValidationScope(unittest.TestCase):
    def test_wave_scope_value(self) -> None:
        normalized, is_all = normalize_wave_scope_value(" secondary1 ")
        self.assertEqual(normalized, "SECONDARY1")
        self.assertFalse(is_all)

        normalized_all, is_all = normalize_wave_scope_value("all")
        self.assertEqual(normalized_all, ALL_SCOPE_TOKEN)
        self.assertTrue(is_all)

    def test_level_filter_values(self) -> None:
        values = normalize_level_filter_values(["elementary,secondary"])
        self.assertEqual(values, {"ELEMENTARY", "SECONDARY"})

    def test_school_scope_value(self) -> None:
        normalized, is_all = normalize_school_scope_value("School #1100")
        self.assertEqual(normalized, "1100")
        self.assertFalse(is_all)

        normalized_all, is_all_all = normalize_school_scope_value("ALL")
        self.assertEqual(normalized_all, "ALL")
        self.assertTrue(is_all_all)

    def test_invalid_scope_values_raise(self) -> None:
        with self.assertRaisesRegex(ValueError, "--wave must be one of"):
            normalize_wave_scope_value("secondary2")
        with self.assertRaisesRegex(ValueError, "--level must be one of"):
            normalize_level_scope_value("middle")
        with self.assertRaisesRegex(
            ValueError, "--school must contain at least one digit"
        ):
            normalize_school_scope_value("abc")
        with self.assertRaisesRegex(
            ValueError, "cannot combine ALL with specific values"
        ):
            normalize_wave_filter_values(["ALL,SECONDARY1"])

    def test_school_filter_values(self) -> None:
        values = normalize_school_id_filter_values(["1100", "School #2200"])
        self.assertEqual(values, {"1100", "2200"})

    def test_parse_scope_selection(self) -> None:
        selection = parse_scope_selection(wave=" secondary1 ", level=None, school=None)
        self.assertEqual(selection.dimension, "wave")
        self.assertEqual(selection.normalized_value, "SECONDARY1")
        self.assertEqual(selection.label, "wave=secondary1")

    def test_scope_uses_custom_allowed_values(self) -> None:
        selection = parse_scope_selection(
            wave="north1",
            level=None,
            school=None,
            allowed_waves={"NORTH1"},
        )
        self.assertEqual(selection.normalized_value, "NORTH1")

        with self.assertRaisesRegex(ValueError, "--wave must be one of"):
            parse_scope_selection(
                wave="south1",
                level=None,
                school=None,
                allowed_waves={"NORTH1"},
            )


if __name__ == "__main__":
    unittest.main()
