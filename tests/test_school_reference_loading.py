from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_ROOT))

from panorama_compliance.reference import collect_scope_values, load_school_reference  # noqa: E402


class TestSchoolReferenceLoading(unittest.TestCase):
    def _write_reference(self, rows: list[dict[str, object]]) -> Path:
        tmp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(tmp_dir.cleanup)
        path = Path(tmp_dir.name) / "school_reference.json"
        path.write_text(json.dumps(rows), encoding="utf-8")
        return path

    def test_loads_wave_windows_when_present(self) -> None:
        path = self._write_reference(
            [
                {
                    "wave": "ELEMENTARY1",
                    "fq_group": "GROUP1",
                    "school_name": "ALPHA SCHOOL",
                    "school_id": "1001",
                    "level": "ELEMENTARY",
                    "suspension_applied_date": "2026-02-09",
                    "suspension_window_start": "2026-02-25",
                    "suspension_window_end": "2026-03-24",
                },
                {
                    "wave": "ELEMENTARY1",
                    "fq_group": "GROUP1",
                    "school_name": "BETA SCHOOL",
                    "school_id": "1002",
                    "level": "ELEMENTARY",
                    "suspension_applied_date": "2026-02-09",
                    "suspension_window_start": "2026-02-25",
                    "suspension_window_end": "2026-03-24",
                },
            ]
        )

        reference = load_school_reference(path)
        self.assertIn("ELEMENTARY1", reference.wave_windows)
        window = reference.wave_windows["ELEMENTARY1"]
        self.assertEqual(window.applied_date.isoformat(), "2026-02-09")
        self.assertEqual(window.suspension_window_start.isoformat(), "2026-02-25")
        self.assertEqual(window.suspension_window_end.isoformat(), "2026-03-24")

    def test_rejects_partial_suspension_window_fields(self) -> None:
        path = self._write_reference(
            [
                {
                    "wave": "SECONDARY1",
                    "fq_group": "GROUPA",
                    "school_name": "ALPHA SECONDARY",
                    "school_id": "3001",
                    "level": "SECONDARY",
                    "suspension_applied_date": "2026-01-28",
                    "suspension_window_start": "2026-02-11",
                }
            ]
        )

        with self.assertRaisesRegex(ValueError, "all or none of suspension window"):
            load_school_reference(path)

    def test_rejects_mixed_window_presence_within_wave(self) -> None:
        path = self._write_reference(
            [
                {
                    "wave": "ELEMENTARY2",
                    "fq_group": "GROUP2",
                    "school_name": "ALPHA ELEMENTARY",
                    "school_id": "1001",
                    "level": "ELEMENTARY",
                    "suspension_applied_date": "2026-03-03",
                    "suspension_window_start": "2026-03-25",
                    "suspension_window_end": "2026-04-21",
                },
                {
                    "wave": "ELEMENTARY2",
                    "fq_group": "GROUP2",
                    "school_name": "BETA ELEMENTARY",
                    "school_id": "1002",
                    "level": "ELEMENTARY",
                },
            ]
        )

        with self.assertRaisesRegex(
            ValueError,
            "all rows in a wave must be consistent",
        ):
            load_school_reference(path)

    def test_collect_scope_values_uses_reference_rows(self) -> None:
        path = self._write_reference(
            [
                {
                    "wave": "WAVE A",
                    "fq_group": "GROUPA",
                    "school_name": "ALPHA SCHOOL",
                    "school_id": "1001",
                    "level": "Grade Group 1",
                },
                {
                    "wave": "WAVE B",
                    "fq_group": "GROUPB",
                    "school_name": "BETA SCHOOL",
                    "school_id": "1002",
                    "level": "Grade Group 2",
                },
            ]
        )
        reference = load_school_reference(path)
        waves, levels = collect_scope_values(reference)
        self.assertEqual(waves, {"WAVEA", "WAVEB"})
        self.assertEqual(levels, {"GRADEGROUP1", "GRADEGROUP2"})


if __name__ == "__main__":
    unittest.main()
