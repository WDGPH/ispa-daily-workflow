from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

import polars as pl

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_ROOT))

from ispa_daily_workflow.domain.delivery.routing import (
    LOCKED_OUTPUT_IDS,
    apply_scope_filter,
    collect_scope_school_labels,
    ensure_scope_non_empty,
    materialize_scoped_outputs,
    parse_scope_selection,
    resolve_compliance_history_paths_for_scope,
)
from ispa_daily_workflow.reference import SchoolReference
from tests.reference_factories import (
    reference_from_records,
    school_record,
)


def _reference() -> SchoolReference:
    record_1001 = school_record(
        school_name="ALPHA SCHOOL",
        school_id="1001",
        level="ELEMENTARY",
        wave="ELEMENTARY1",
        fq_group="GROUP_A",
    )
    record_1002 = school_record(
        school_name="BETA SCHOOL",
        school_id="1002",
        level="SECONDARY",
        wave="SECONDARY1",
        fq_group="GROUP_B",
    )
    return reference_from_records(
        [record_1001, record_1002],
        with_wave_windows=False,
    )


class TestDeliveryHelpers(unittest.TestCase):
    def test_locked_output_ids(self) -> None:
        self.assertEqual(
            LOCKED_OUTPUT_IDS,
            (
                "sharepoint.panorama.diff.xlsx",
                "sharepoint.action_queue.xlsx",
                "sharepoint.overdue.pdf",
                "sharepoint.suspension.pdf",
            ),
        )

    def test_scope_requires_exactly_one_flag(self) -> None:
        with self.assertRaisesRegex(ValueError, "Exactly one"):
            parse_scope_selection(wave=None, level=None, school=None)
        with self.assertRaisesRegex(ValueError, "Exactly one"):
            parse_scope_selection(wave="SECONDARY1", level="SECONDARY", school=None)

    def test_scope_normalization(self) -> None:
        scope_wave = parse_scope_selection(
            wave=" secondary 1 ", level=None, school=None
        )
        self.assertEqual(scope_wave.dimension, "wave")
        self.assertEqual(scope_wave.normalized_value, "SECONDARY1")
        self.assertFalse(scope_wave.is_all)

        scope_level = parse_scope_selection(wave=None, level="elementary", school=None)
        self.assertEqual(scope_level.dimension, "level")
        self.assertEqual(scope_level.normalized_value, "ELEMENTARY")
        self.assertFalse(scope_level.is_all)

        scope_school = parse_scope_selection(
            wave=None, level=None, school="School #1002"
        )
        self.assertEqual(scope_school.dimension, "school")
        self.assertEqual(scope_school.normalized_value, "1002")
        self.assertFalse(scope_school.is_all)

        scope_all = parse_scope_selection(wave="ALL", level=None, school=None)
        self.assertTrue(scope_all.is_all)
        self.assertEqual(scope_all.normalized_value, "ALL")

    def test_missing_compliance_history_raises(self) -> None:
        scope = parse_scope_selection(wave="ALL", level=None, school=None)
        with tempfile.TemporaryDirectory() as tmp:
            compliance_history_dir = Path(tmp)
            with self.assertRaisesRegex(
                RuntimeError, "No compliance_history snapshots"
            ):
                resolve_compliance_history_paths_for_scope(
                    compliance_history_dir=compliance_history_dir,
                    run_date="20260210",
                    scope=scope,
                )

    def test_wave_scope_selects_single_slice(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            compliance_history_dir = Path(tmp)
            (
                compliance_history_dir
                / "20260210_panorama_secondary1_compliance_history.parquet"
            ).touch()
            (
                compliance_history_dir
                / "20260210_panorama_elementary1_compliance_history.parquet"
            ).touch()

            scope = parse_scope_selection(wave="secondary1", level=None, school=None)
            selected = resolve_compliance_history_paths_for_scope(
                compliance_history_dir=compliance_history_dir,
                run_date="20260210",
                scope=scope,
            )
            self.assertEqual(set(selected.keys()), {"secondary1"})

    def test_exact_run_date_requires_exact_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            compliance_history_dir = Path(tmp)
            (
                compliance_history_dir
                / "20260209_panorama_secondary1_compliance_history.parquet"
            ).touch()
            scope = parse_scope_selection(wave="ALL", level=None, school=None)
            with self.assertRaisesRegex(RuntimeError, "for run_date=20260210"):
                resolve_compliance_history_paths_for_scope(
                    compliance_history_dir=compliance_history_dir,
                    run_date="20260210",
                    scope=scope,
                    exact_run_date=True,
                )

    def test_invalid_wave_and_level_scope_values_raise(self) -> None:
        with self.assertRaisesRegex(ValueError, "--wave must be one of"):
            parse_scope_selection(wave="secondary2", level=None, school=None)
        with self.assertRaisesRegex(ValueError, "--level must be one of"):
            parse_scope_selection(wave=None, level="middle", school=None)

    def test_apply_scope_filter_level_and_school(self) -> None:
        frame = pl.DataFrame(
            {
                "client_id": ["c1", "c2", "c3"],
                "school_id": ["1001", "1002", "1002"],
            }
        )
        reference = _reference()

        level_scope = parse_scope_selection(wave=None, level="secondary", school=None)
        filtered_level = apply_scope_filter(
            frame, scope=level_scope, reference=reference
        )
        self.assertEqual(filtered_level.height, 2)

        school_scope = parse_scope_selection(wave=None, level=None, school="1001")
        filtered_school = apply_scope_filter(
            frame, scope=school_scope, reference=reference
        )
        self.assertEqual(filtered_school.height, 1)
        self.assertEqual(filtered_school.get_column("school_id").to_list(), ["1001"])

    def test_collect_scope_school_labels_filters_by_scope(self) -> None:
        reference = _reference()

        level_scope = parse_scope_selection(wave=None, level="secondary", school=None)
        labels = collect_scope_school_labels(scope=level_scope, reference=reference)
        self.assertEqual(labels, ["BETA SCHOOL - 1002"])

        school_scope = parse_scope_selection(wave=None, level=None, school="1001")
        labels = collect_scope_school_labels(scope=school_scope, reference=reference)
        self.assertEqual(labels, ["ALPHA SCHOOL - 1001"])

    def test_collect_scope_school_labels_respects_allowed_slice_tokens(self) -> None:
        reference = _reference()
        all_scope = parse_scope_selection(wave="ALL", level=None, school=None)

        labels = collect_scope_school_labels(
            scope=all_scope,
            reference=reference,
            allowed_slice_tokens={"secondary1"},
        )
        self.assertEqual(labels, ["BETA SCHOOL - 1002"])

    def test_scope_empty_raises(self) -> None:
        scope = parse_scope_selection(wave="ALL", level=None, school=None)
        with self.assertRaisesRegex(RuntimeError, "resolved to zero rows"):
            ensure_scope_non_empty(
                frames_by_slice={"secondary1": pl.DataFrame()},
                scope=scope,
                label="diff",
            )

    def test_materialize_outputs_dry_run_does_not_write(self) -> None:
        def write_marker(_frame: pl.DataFrame, path: Path) -> None:
            path.write_text("written", encoding="utf-8")

        frames_by_slice = {"secondary1": pl.DataFrame({"client_id": ["c1"]})}
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp) / "out"
            outputs = materialize_scoped_outputs(
                frames_by_slice=frames_by_slice,
                output_dir=output_dir,
                filename_builder=lambda slice_token: f"{slice_token}.txt",
                writer=write_marker,
                dry_run=True,
            )
            self.assertEqual(outputs, [output_dir / "secondary1.txt"])
            self.assertFalse((output_dir / "secondary1.txt").exists())


if __name__ == "__main__":
    unittest.main()
