from __future__ import annotations

import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

import polars as pl

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_ROOT))

from ispa_daily_workflow.pipeline.deliver_outputs import (
    _empty_action_queue_frames_for_scope,
    _is_empty_processed_action_queue_snapshot,
    _resolve_pear_state_paths,
    parse_scope_selection,
)
from ispa_daily_workflow.reference import SchoolReference
from tests.reference_factories import (
    reference_from_records,
    school_record,
)


def _reference() -> SchoolReference:
    record_elementary = school_record(
        school_name="ALPHA SCHOOL",
        school_id="1001",
        level="ELEMENTARY",
        wave="ELEMENTARY1",
        fq_group="GROUP_A",
    )
    record_secondary = school_record(
        school_name="BETA SCHOOL",
        school_id="1002",
        level="SECONDARY",
        wave="SECONDARY1",
        fq_group="GROUP_B",
    )
    return reference_from_records(
        [record_elementary, record_secondary],
        secondary_labels={"BETA SCHOOL - 1002"},
        with_wave_windows=False,
    )


class TestDeliverOutputsActionQueue(unittest.TestCase):
    def test_resolve_pear_action_queue_paths_for_wave_scope(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state_dir = Path(tmp)
            (
                state_dir / "20260224_pear_secondary1_suspension_vs_overdue.parquet"
            ).touch()
            (
                state_dir / "20260224_pear_elementary1_suspension_vs_overdue.parquet"
            ).touch()

            scope = parse_scope_selection(wave="SECONDARY1", level=None, school=None)
            resolved = _resolve_pear_state_paths(
                pear_state_dir=state_dir,
                state_name="suspension_vs_overdue",
                run_date="20260224",
                scope=scope,
            )
            self.assertEqual(set(resolved.keys()), {"secondary1"})

    def test_resolve_pear_action_queue_paths_raises_when_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state_dir = Path(tmp)
            scope = parse_scope_selection(wave="ALL", level=None, school=None)
            with self.assertRaisesRegex(RuntimeError, "No PEAR suspension_vs_overdue"):
                _resolve_pear_state_paths(
                    pear_state_dir=state_dir,
                    state_name="suspension_vs_overdue",
                    run_date="20260224",
                    scope=scope,
                )

    def test_empty_action_queue_fallback_frames_cover_scope_slices(self) -> None:
        scope = parse_scope_selection(wave="ALL", level=None, school=None)
        frames = _empty_action_queue_frames_for_scope(
            scope=scope,
            reference=_reference(),
        )
        self.assertEqual(set(frames.keys()), {"elementary1", "secondary1"})
        self.assertTrue(all(frame.is_empty() for frame in frames.values()))

    def test_empty_processed_action_queue_detector(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            processed_dir = Path(tmp)
            empty_path = processed_dir / "20260224_suspension_vs_overdue.parquet"
            pl.DataFrame(
                schema={
                    "client_id": pl.Utf8,
                    "school_id": pl.Utf8,
                    "school_name": pl.Utf8,
                    "first_name": pl.Utf8,
                    "last_name": pl.Utf8,
                    "date_of_birth": pl.Date,
                    "action_required": pl.Utf8,
                    "action_date": pl.Date,
                }
            ).write_parquet(empty_path)
            self.assertTrue(
                _is_empty_processed_action_queue_snapshot(
                    pear_processed_dir=processed_dir,
                    run_date="20260224",
                )
            )

            pl.DataFrame(
                [
                    {
                        "client_id": "0000000001",
                        "school_id": "1001",
                        "school_name": "ALPHA SCHOOL",
                        "first_name": "A",
                        "last_name": "ONE",
                        "date_of_birth": date(2012, 1, 1),
                        "action_required": "rescind",
                        "action_date": date(2026, 2, 24),
                    }
                ]
            ).write_parquet(empty_path)
            self.assertFalse(
                _is_empty_processed_action_queue_snapshot(
                    pear_processed_dir=processed_dir,
                    run_date="20260224",
                )
            )

    def test_empty_processed_action_queue_detector_wave_sliced(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            processed_dir = Path(tmp)
            elementary_path = (
                processed_dir
                / "20260224_pear_suspension_vs_overdue_elementary1.parquet"
            )
            secondary_path = (
                processed_dir / "20260224_pear_suspension_vs_overdue_secondary1.parquet"
            )
            pl.DataFrame(
                schema={
                    "client_id": pl.Utf8,
                    "school_id": pl.Utf8,
                    "school_name": pl.Utf8,
                    "first_name": pl.Utf8,
                    "last_name": pl.Utf8,
                    "date_of_birth": pl.Date,
                    "action_required": pl.Utf8,
                    "action_date": pl.Date,
                }
            ).write_parquet(elementary_path)
            pl.DataFrame(
                schema={
                    "client_id": pl.Utf8,
                    "school_id": pl.Utf8,
                    "school_name": pl.Utf8,
                    "first_name": pl.Utf8,
                    "last_name": pl.Utf8,
                    "date_of_birth": pl.Date,
                    "action_required": pl.Utf8,
                    "action_date": pl.Date,
                }
            ).write_parquet(secondary_path)
            self.assertTrue(
                _is_empty_processed_action_queue_snapshot(
                    pear_processed_dir=processed_dir,
                    run_date="20260224",
                )
            )

            pl.DataFrame(
                [
                    {
                        "client_id": "0000000001",
                        "school_id": "1001",
                        "school_name": "ALPHA SCHOOL",
                        "first_name": "A",
                        "last_name": "ONE",
                        "date_of_birth": date(2012, 1, 1),
                        "action_required": "rescind",
                        "action_date": date(2026, 2, 24),
                    }
                ]
            ).write_parquet(secondary_path)
            self.assertFalse(
                _is_empty_processed_action_queue_snapshot(
                    pear_processed_dir=processed_dir,
                    run_date="20260224",
                )
            )

    def test_resolve_pear_action_queue_paths_requires_exact_run_date(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state_dir = Path(tmp)
            (
                state_dir / "20260223_pear_secondary1_suspension_vs_overdue.parquet"
            ).touch()
            scope = parse_scope_selection(wave="ALL", level=None, school=None)
            with self.assertRaisesRegex(RuntimeError, "run_date=20260224"):
                _resolve_pear_state_paths(
                    pear_state_dir=state_dir,
                    state_name="suspension_vs_overdue",
                    run_date="20260224",
                    scope=scope,
                )


if __name__ == "__main__":
    unittest.main()
