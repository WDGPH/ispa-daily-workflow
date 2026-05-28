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

from ispa_daily_workflow.pear_state import (
    derive_pear_state,
    discover_latest_pear_authoritative_baseline_by_slice,
    discover_latest_pear_processed_inputs,
    write_pear_authoritative_suspension_outputs,
    write_pear_state_outputs,
)
from ispa_daily_workflow.schema import ValidationError
from tests.reference_factories import (
    alpha_beta_reference,
    alpha_school_reference,
    business_workdays,
)


class TestPearStateDerive(unittest.TestCase):
    def test_discovery_selects_latest_available_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            processed_dir = Path(tmp)
            for name in (
                "20260220_suspension_list_elementary.parquet",
                "20260220_suspension_list_secondary.parquet",
                "20260219_suspension_list_secondary.parquet",
                "20260219_overdue_list_pear.parquet",
                "20260223_overdue_list_pear.parquet",
                "20260221_suspension_vs_overdue.parquet",
                "20260222_suspension_vs_overdue.parquet",
            ):
                (processed_dir / name).touch()

            selection = discover_latest_pear_processed_inputs(
                processed_dir=processed_dir,
                run_date="20260222",
            )

            self.assertEqual(selection.selected_dates["suspension_active"], "20260220")
            self.assertEqual(selection.selected_dates["overdue_active"], "20260219")
            self.assertEqual(
                selection.selected_dates["suspension_vs_overdue"], "20260222"
            )
            self.assertEqual(len(selection.suspension_paths), 2)
            self.assertEqual(selection.previous_suspension_date, "20260219")
            self.assertEqual(len(selection.previous_suspension_paths), 1)
            self.assertEqual(
                selection.suspension_vs_overdue_path.name,
                "20260222_suspension_vs_overdue.parquet",
            )

    def test_discovery_prefers_wave_sliced_processed_contract(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            processed_dir = Path(tmp)
            for name in (
                "20260224_pear_suspension_list_elementary1.parquet",
                "20260224_pear_suspension_list_secondary1.parquet",
                "20260223_pear_suspension_list_elementary1.parquet",
                "20260223_pear_suspension_list_secondary1.parquet",
                "20260224_pear_overdue_list_elementary1.parquet",
                "20260224_pear_overdue_list_secondary1.parquet",
                "20260224_pear_suspension_vs_overdue_elementary1.parquet",
                "20260224_pear_suspension_vs_overdue_secondary1.parquet",
            ):
                (processed_dir / name).touch()

            selection = discover_latest_pear_processed_inputs(
                processed_dir=processed_dir,
                run_date="20260224",
            )

            self.assertEqual(selection.selected_dates["suspension_active"], "20260224")
            self.assertEqual(selection.selected_dates["overdue_active"], "20260224")
            self.assertEqual(
                selection.selected_dates["suspension_vs_overdue"],
                "20260224",
            )
            self.assertEqual(
                sorted(path.name for path in selection.suspension_paths),
                [
                    "20260224_pear_suspension_list_elementary1.parquet",
                    "20260224_pear_suspension_list_secondary1.parquet",
                ],
            )
            self.assertEqual(selection.previous_suspension_date, "20260223")

    def test_derive_and_write_wave_sliced_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            processed_dir = tmp_path / "processed"
            output_dir = tmp_path / "state"
            processed_dir.mkdir(parents=True, exist_ok=True)

            pl.DataFrame(
                [
                    {
                        "client_id": "0000000001",
                        "school_id": "1001",
                        "school_name": "ALPHA ELEMENTARY SCHOOL",
                        "first_name": "A",
                        "last_name": "One",
                        "date_of_birth": date(2012, 1, 1),
                        "rescind_date": None,
                    }
                ]
            ).write_parquet(
                processed_dir / "20260224_suspension_list_elementary.parquet"
            )
            pl.DataFrame(
                [
                    {
                        "client_id": "0000000002",
                        "school_id": "3001",
                        "school_name": "BETA SECONDARY SCHOOL",
                        "first_name": "B",
                        "last_name": "Two",
                        "date_of_birth": date(2011, 2, 2),
                        "rescind_date": None,
                    }
                ]
            ).write_parquet(
                processed_dir / "20260224_suspension_list_secondary.parquet"
            )
            pl.DataFrame(
                [
                    {
                        "client_id": "0000000003",
                        "school_id": "1001",
                        "school_name": "ALPHA ELEMENTARY SCHOOL",
                        "first_name": "C",
                        "last_name": "Three",
                        "date_of_birth": date(2013, 3, 3),
                        "overdue_agents": "MMR",
                    },
                    {
                        "client_id": "0000000004",
                        "school_id": "3001",
                        "school_name": "BETA SECONDARY SCHOOL",
                        "first_name": "D",
                        "last_name": "Four",
                        "date_of_birth": date(2014, 4, 4),
                        "overdue_agents": "Tdap",
                    },
                ]
            ).write_parquet(processed_dir / "20260224_overdue_list_pear.parquet")
            pl.DataFrame(
                [
                    {
                        "client_id": "0000000005",
                        "school_id": "1001",
                        "school_name": "ALPHA ELEMENTARY SCHOOL",
                        "first_name": "E",
                        "last_name": "Five",
                        "date_of_birth": date(2015, 5, 5),
                        "action_required": "delete",
                        "action_date": date(2026, 2, 24),
                    }
                ]
            ).write_parquet(processed_dir / "20260224_suspension_vs_overdue.parquet")

            selection = discover_latest_pear_processed_inputs(
                processed_dir=processed_dir,
                run_date="20260224",
            )
            result = derive_pear_state(
                selection=selection,
                schema_root=PROJECT_ROOT / "schema",
                reference=alpha_beta_reference(),
            )

            self.assertEqual(result.frames["suspension_active"].height, 2)
            self.assertEqual(result.frames["suspension_operational"].height, 2)
            self.assertEqual(result.frames["overdue_active"].height, 2)
            self.assertEqual(result.frames["suspension_vs_overdue"].height, 1)
            self.assertIn("wave", result.frames["suspension_active"].columns)
            self.assertIn("level", result.frames["suspension_active"].columns)
            self.assertEqual(result.disappearance_summary["disappeared_count"], 0)
            self.assertEqual(result.disappearance_evidence.height, 0)

            written = write_pear_state_outputs(
                frames=result.frames,
                run_date="20260224",
                output_dir=output_dir,
            )
            written_names = sorted(path.name for path in written)
            self.assertEqual(
                written_names,
                [
                    "20260224_pear_elementary1_overdue_active.parquet",
                    "20260224_pear_elementary1_suspension_active.parquet",
                    "20260224_pear_elementary1_suspension_operational.parquet",
                    "20260224_pear_elementary1_suspension_vs_overdue.parquet",
                    "20260224_pear_secondary1_overdue_active.parquet",
                    "20260224_pear_secondary1_suspension_active.parquet",
                    "20260224_pear_secondary1_suspension_operational.parquet",
                ],
            )

    def test_rehydrates_unresolved_suspension_disappearances(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            processed_dir = Path(tmp)
            pl.DataFrame(
                [
                    {
                        "client_id": "0000000001",
                        "school_id": "1001",
                        "school_name": "ALPHA ELEMENTARY SCHOOL",
                        "first_name": "A",
                        "last_name": "One",
                        "date_of_birth": date(2012, 1, 1),
                        "rescind_date": None,
                    }
                ]
            ).write_parquet(
                processed_dir / "20260224_suspension_list_elementary.parquet"
            )
            pl.DataFrame(
                [
                    {
                        "client_id": "0000000002",
                        "school_id": "1001",
                        "school_name": "ALPHA ELEMENTARY SCHOOL",
                        "first_name": "B",
                        "last_name": "Two",
                        "date_of_birth": date(2012, 2, 2),
                        "rescind_date": None,
                    }
                ]
            ).write_parquet(
                processed_dir / "20260225_suspension_list_elementary.parquet"
            )
            pl.DataFrame(
                [
                    {
                        "client_id": "0000000003",
                        "school_id": "1001",
                        "school_name": "ALPHA ELEMENTARY SCHOOL",
                        "first_name": "C",
                        "last_name": "Three",
                        "date_of_birth": date(2012, 3, 3),
                        "overdue_agents": "MMR",
                    }
                ]
            ).write_parquet(processed_dir / "20260225_overdue_list_pear.parquet")
            pl.DataFrame(
                [
                    {
                        "client_id": "0000000010",
                        "school_id": "1001",
                        "school_name": "ALPHA ELEMENTARY SCHOOL",
                        "first_name": "Z",
                        "last_name": "Ten",
                        "date_of_birth": date(2012, 10, 10),
                        "action_required": "rescind",
                        "action_date": date(2026, 2, 24),
                    }
                ]
            ).write_parquet(processed_dir / "20260225_suspension_vs_overdue.parquet")

            selection = discover_latest_pear_processed_inputs(
                processed_dir=processed_dir,
                run_date="20260225",
            )
            result = derive_pear_state(
                selection=selection,
                schema_root=PROJECT_ROOT / "schema",
                reference=alpha_beta_reference(),
            )

            self.assertEqual(result.disappearance_summary["disappeared_count"], 1)
            self.assertEqual(result.disappearance_summary["resolved_count"], 0)
            self.assertEqual(result.disappearance_summary["unresolved_count"], 1)
            self.assertEqual(result.disappearance_summary["rehydrated_count"], 1)
            self.assertEqual(result.disappearance_evidence.height, 1)
            self.assertEqual(
                result.disappearance_evidence.get_column("resolution_status").to_list(),
                ["restored_assumed_dropoff_rescind_missing_evidence"],
            )
            self.assertEqual(
                result.disappearance_evidence.get_column("rescind_date").to_list(),
                [date(2026, 2, 25)],
            )
            self.assertEqual(result.critical_messages, ())
            self.assertEqual(len(result.warning_messages), 1)
            self.assertEqual(result.frames["suspension_active"].height, 2)
            self.assertEqual(result.frames["suspension_operational"].height, 2)

    def test_patches_rescind_dates_and_keeps_rescind_rows_operational(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            processed_dir = Path(tmp)
            pl.DataFrame(
                [
                    {
                        "client_id": "0000000001",
                        "school_id": "1001",
                        "school_name": "ALPHA ELEMENTARY SCHOOL",
                        "first_name": "A",
                        "last_name": "One",
                        "date_of_birth": date(2012, 1, 1),
                        "rescind_date": None,
                    },
                    {
                        "client_id": "0000000002",
                        "school_id": "1001",
                        "school_name": "ALPHA ELEMENTARY SCHOOL",
                        "first_name": "B",
                        "last_name": "Two",
                        "date_of_birth": date(2012, 2, 2),
                        "rescind_date": None,
                    },
                ]
            ).write_parquet(
                processed_dir / "20260224_suspension_list_elementary.parquet"
            )
            pl.DataFrame(
                [
                    {
                        "client_id": "0000000003",
                        "school_id": "1001",
                        "school_name": "ALPHA ELEMENTARY SCHOOL",
                        "first_name": "C",
                        "last_name": "Three",
                        "date_of_birth": date(2012, 3, 3),
                        "overdue_agents": "MMR",
                    }
                ]
            ).write_parquet(processed_dir / "20260224_overdue_list_pear.parquet")
            pl.DataFrame(
                [
                    {
                        "client_id": "0000000001",
                        "school_id": "1001",
                        "school_name": "ALPHA ELEMENTARY SCHOOL",
                        "first_name": "A",
                        "last_name": "One",
                        "date_of_birth": date(2012, 1, 1),
                        "action_required": "rescind",
                        "action_date": date(2026, 2, 25),
                    },
                    {
                        "client_id": "0000000002",
                        "school_id": "1001",
                        "school_name": "ALPHA ELEMENTARY SCHOOL",
                        "first_name": "B",
                        "last_name": "Two",
                        "date_of_birth": date(2012, 2, 2),
                        "action_required": "delete",
                        "action_date": date(2026, 2, 24),
                    },
                ]
            ).write_parquet(processed_dir / "20260224_suspension_vs_overdue.parquet")

            selection = discover_latest_pear_processed_inputs(
                processed_dir=processed_dir,
                run_date="20260224",
            )
            result = derive_pear_state(
                selection=selection,
                schema_root=PROJECT_ROOT / "schema",
                reference=alpha_beta_reference(),
            )

            suspension_active = result.frames["suspension_active"]
            patched_rescind = suspension_active.filter(
                pl.col("client_id") == "0000000001"
            ).get_column("rescind_date")[0]
            self.assertEqual(patched_rescind, date(2026, 2, 25))

            suspension_operational = result.frames["suspension_operational"]
            self.assertEqual(suspension_operational.height, 1)
            self.assertEqual(
                suspension_operational.get_column("client_id").to_list(),
                ["0000000001"],
            )
            self.assertEqual(result.rescind_patch_summary["patched_rescind_rows"], 1)
            self.assertEqual(result.rescind_patch_summary["matched_delete_rows"], 1)

    def test_restores_disappearance_when_action_evidence_exists(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            processed_dir = Path(tmp)
            pl.DataFrame(
                [
                    {
                        "client_id": "0000000001",
                        "school_id": "1001",
                        "school_name": "ALPHA ELEMENTARY SCHOOL",
                        "first_name": "A",
                        "last_name": "One",
                        "date_of_birth": date(2012, 1, 1),
                        "rescind_date": None,
                    }
                ]
            ).write_parquet(
                processed_dir / "20260224_suspension_list_elementary.parquet"
            )
            pl.DataFrame(
                [
                    {
                        "client_id": "0000000002",
                        "school_id": "1001",
                        "school_name": "ALPHA ELEMENTARY SCHOOL",
                        "first_name": "B",
                        "last_name": "Two",
                        "date_of_birth": date(2012, 2, 2),
                        "rescind_date": None,
                    }
                ]
            ).write_parquet(
                processed_dir / "20260225_suspension_list_elementary.parquet"
            )
            pl.DataFrame(
                [
                    {
                        "client_id": "0000000003",
                        "school_id": "1001",
                        "school_name": "ALPHA ELEMENTARY SCHOOL",
                        "first_name": "C",
                        "last_name": "Three",
                        "date_of_birth": date(2012, 3, 3),
                        "overdue_agents": "MMR",
                    }
                ]
            ).write_parquet(processed_dir / "20260225_overdue_list_pear.parquet")
            pl.DataFrame(
                [
                    {
                        "client_id": "0000000001",
                        "school_id": "1001",
                        "school_name": "ALPHA ELEMENTARY SCHOOL",
                        "first_name": "A",
                        "last_name": "One",
                        "date_of_birth": date(2012, 1, 1),
                        "action_required": "rescind",
                        "action_date": date(2026, 2, 25),
                    }
                ]
            ).write_parquet(processed_dir / "20260225_suspension_vs_overdue.parquet")

            selection = discover_latest_pear_processed_inputs(
                processed_dir=processed_dir,
                run_date="20260225",
            )
            result = derive_pear_state(
                selection=selection,
                schema_root=PROJECT_ROOT / "schema",
                reference=alpha_beta_reference(),
            )

            self.assertEqual(result.disappearance_summary["disappeared_count"], 1)
            self.assertEqual(result.disappearance_summary["resolved_count"], 1)
            self.assertEqual(result.disappearance_summary["unresolved_count"], 0)
            self.assertEqual(result.disappearance_summary["rehydrated_count"], 1)
            self.assertEqual(result.frames["suspension_active"].height, 2)
            self.assertEqual(result.frames["suspension_operational"].height, 2)
            restored_rescind_date = (
                result.frames["suspension_active"]
                .filter(pl.col("client_id") == "0000000001")
                .get_column("rescind_date")[0]
            )
            self.assertEqual(restored_rescind_date, date(2026, 2, 25))
            self.assertEqual(len(result.warning_messages), 1)
            self.assertIn(
                "resolution_status=restored_action_rescind", result.warning_messages[0]
            )
            self.assertEqual(result.critical_messages, ())

    def test_delete_action_does_not_resolve_disappearance(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            processed_dir = Path(tmp)
            pl.DataFrame(
                [
                    {
                        "client_id": "0000000001",
                        "school_id": "1001",
                        "school_name": "ALPHA ELEMENTARY SCHOOL",
                        "first_name": "A",
                        "last_name": "One",
                        "date_of_birth": date(2012, 1, 1),
                        "rescind_date": None,
                    }
                ]
            ).write_parquet(
                processed_dir / "20260224_suspension_list_elementary.parquet"
            )
            pl.DataFrame(
                [
                    {
                        "client_id": "0000000002",
                        "school_id": "1001",
                        "school_name": "ALPHA ELEMENTARY SCHOOL",
                        "first_name": "B",
                        "last_name": "Two",
                        "date_of_birth": date(2012, 2, 2),
                        "rescind_date": None,
                    }
                ]
            ).write_parquet(
                processed_dir / "20260225_suspension_list_elementary.parquet"
            )
            pl.DataFrame(
                [
                    {
                        "client_id": "0000000003",
                        "school_id": "1001",
                        "school_name": "ALPHA ELEMENTARY SCHOOL",
                        "first_name": "C",
                        "last_name": "Three",
                        "date_of_birth": date(2012, 3, 3),
                        "overdue_agents": "MMR",
                    }
                ]
            ).write_parquet(processed_dir / "20260225_overdue_list_pear.parquet")
            pl.DataFrame(
                [
                    {
                        "client_id": "0000000001",
                        "school_id": "1001",
                        "school_name": "ALPHA ELEMENTARY SCHOOL",
                        "first_name": "A",
                        "last_name": "One",
                        "date_of_birth": date(2012, 1, 1),
                        "action_required": "delete",
                        "action_date": date(2026, 2, 25),
                    }
                ]
            ).write_parquet(processed_dir / "20260225_suspension_vs_overdue.parquet")

            selection = discover_latest_pear_processed_inputs(
                processed_dir=processed_dir,
                run_date="20260225",
            )
            result = derive_pear_state(
                selection=selection,
                schema_root=PROJECT_ROOT / "schema",
                reference=alpha_beta_reference(),
            )

            self.assertEqual(result.disappearance_summary["disappeared_count"], 1)
            self.assertEqual(result.disappearance_summary["resolved_count"], 0)
            self.assertEqual(result.disappearance_summary["unresolved_count"], 1)
            self.assertEqual(result.disappearance_summary["rehydrated_count"], 1)
            self.assertEqual(
                result.disappearance_evidence.get_column("evidence_source").to_list(),
                ["suspension_vs_overdue_delete_without_rescind"],
            )
            self.assertEqual(
                result.disappearance_evidence.get_column("resolution_status").to_list(),
                ["restored_assumed_dropoff_rescind_after_delete"],
            )
            self.assertEqual(
                result.disappearance_evidence.get_column("rescind_date").to_list(),
                [date(2026, 2, 25)],
            )
            self.assertEqual(result.frames["suspension_operational"].height, 2)
            self.assertEqual(result.critical_messages, ())

    def test_restores_disappearance_with_prior_rescind_date(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            processed_dir = Path(tmp)
            pl.DataFrame(
                [
                    {
                        "client_id": "0000000001",
                        "school_id": "1001",
                        "school_name": "ALPHA ELEMENTARY SCHOOL",
                        "first_name": "A",
                        "last_name": "One",
                        "date_of_birth": date(2012, 1, 1),
                        "rescind_date": date(2026, 2, 25),
                    }
                ]
            ).write_parquet(
                processed_dir / "20260224_suspension_list_elementary.parquet"
            )
            pl.DataFrame(
                [
                    {
                        "client_id": "0000000002",
                        "school_id": "1001",
                        "school_name": "ALPHA ELEMENTARY SCHOOL",
                        "first_name": "B",
                        "last_name": "Two",
                        "date_of_birth": date(2012, 2, 2),
                        "rescind_date": None,
                    }
                ]
            ).write_parquet(
                processed_dir / "20260225_suspension_list_elementary.parquet"
            )
            pl.DataFrame(
                [
                    {
                        "client_id": "0000000003",
                        "school_id": "1001",
                        "school_name": "ALPHA ELEMENTARY SCHOOL",
                        "first_name": "C",
                        "last_name": "Three",
                        "date_of_birth": date(2012, 3, 3),
                        "overdue_agents": "MMR",
                    }
                ]
            ).write_parquet(processed_dir / "20260225_overdue_list_pear.parquet")
            pl.DataFrame(
                [
                    {
                        "client_id": "0000000010",
                        "school_id": "1001",
                        "school_name": "ALPHA ELEMENTARY SCHOOL",
                        "first_name": "Z",
                        "last_name": "Ten",
                        "date_of_birth": date(2012, 10, 10),
                        "action_required": "delete",
                        "action_date": date(2026, 2, 25),
                    }
                ]
            ).write_parquet(processed_dir / "20260225_suspension_vs_overdue.parquet")

            selection = discover_latest_pear_processed_inputs(
                processed_dir=processed_dir,
                run_date="20260225",
            )
            result = derive_pear_state(
                selection=selection,
                schema_root=PROJECT_ROOT / "schema",
                reference=alpha_beta_reference(),
            )

            self.assertEqual(result.disappearance_summary["disappeared_count"], 1)
            self.assertEqual(result.disappearance_summary["resolved_count"], 1)
            self.assertEqual(result.disappearance_summary["unresolved_count"], 0)
            self.assertEqual(result.disappearance_summary["rehydrated_count"], 1)
            self.assertEqual(
                result.disappearance_evidence.get_column("resolution_status").to_list(),
                ["restored_prior_rescind_date"],
            )
            self.assertEqual(
                result.disappearance_evidence.get_column("rescind_date").to_list(),
                [date(2026, 2, 25)],
            )
            restored_row = result.frames["suspension_active"].filter(
                pl.col("client_id") == "0000000001"
            )
            self.assertEqual(restored_row.height, 1)
            self.assertEqual(
                restored_row.get_column("rescind_date")[0], date(2026, 2, 25)
            )
            self.assertEqual(len(result.warning_messages), 1)
            self.assertIn(
                "resolution_status=restored_prior_rescind_date",
                result.warning_messages[0],
            )
            self.assertEqual(result.critical_messages, ())

    def test_hard_fails_when_rescind_before_wave_window_start(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            processed_dir = Path(tmp)
            pl.DataFrame(
                [
                    {
                        "client_id": "0000000001",
                        "school_id": "1001",
                        "school_name": "ALPHA ELEMENTARY SCHOOL",
                        "first_name": "A",
                        "last_name": "One",
                        "date_of_birth": date(2012, 1, 1),
                        "rescind_date": date(2026, 2, 24),
                    }
                ]
            ).write_parquet(
                processed_dir / "20260224_suspension_list_elementary.parquet"
            )
            pl.DataFrame(
                [
                    {
                        "client_id": "0000000003",
                        "school_id": "1001",
                        "school_name": "ALPHA ELEMENTARY SCHOOL",
                        "first_name": "C",
                        "last_name": "Three",
                        "date_of_birth": date(2012, 3, 3),
                        "overdue_agents": "MMR",
                    }
                ]
            ).write_parquet(processed_dir / "20260224_overdue_list_pear.parquet")
            pl.DataFrame(
                [
                    {
                        "client_id": "0000000010",
                        "school_id": "1001",
                        "school_name": "ALPHA ELEMENTARY SCHOOL",
                        "first_name": "Z",
                        "last_name": "Ten",
                        "date_of_birth": date(2012, 10, 10),
                        "action_required": "delete",
                        "action_date": date(2026, 2, 24),
                    }
                ]
            ).write_parquet(processed_dir / "20260224_suspension_vs_overdue.parquet")

            selection = discover_latest_pear_processed_inputs(
                processed_dir=processed_dir,
                run_date="20260224",
            )
            with self.assertRaisesRegex(ValidationError, "ISPA-03-010"):
                derive_pear_state(
                    selection=selection,
                    schema_root=PROJECT_ROOT / "schema",
                    reference=alpha_beta_reference(),
                )

    def test_hard_fails_when_previous_business_day_suspension_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            processed_dir = Path(tmp)
            pl.DataFrame(
                [
                    {
                        "client_id": "0000000002",
                        "school_id": "1001",
                        "school_name": "ALPHA ELEMENTARY SCHOOL",
                        "first_name": "B",
                        "last_name": "Two",
                        "date_of_birth": date(2012, 2, 2),
                        "rescind_date": None,
                    }
                ]
            ).write_parquet(
                processed_dir / "20260225_suspension_list_elementary.parquet"
            )
            pl.DataFrame(
                [
                    {
                        "client_id": "0000000003",
                        "school_id": "1001",
                        "school_name": "ALPHA ELEMENTARY SCHOOL",
                        "first_name": "C",
                        "last_name": "Three",
                        "date_of_birth": date(2012, 3, 3),
                        "overdue_agents": "MMR",
                    }
                ]
            ).write_parquet(processed_dir / "20260225_overdue_list_pear.parquet")
            pl.DataFrame(
                [
                    {
                        "client_id": "0000000001",
                        "school_id": "1001",
                        "school_name": "ALPHA ELEMENTARY SCHOOL",
                        "first_name": "A",
                        "last_name": "One",
                        "date_of_birth": date(2012, 1, 1),
                        "action_required": "rescind",
                        "action_date": date(2026, 2, 25),
                    }
                ]
            ).write_parquet(processed_dir / "20260225_suspension_vs_overdue.parquet")

            selection = discover_latest_pear_processed_inputs(
                processed_dir=processed_dir,
                run_date="20260225",
            )
            with self.assertRaisesRegex(
                ValidationError,
                "missing previous business day suspension list "
                "20260224_suspension_list_elementary.parquet",
            ):
                derive_pear_state(
                    selection=selection,
                    schema_root=PROJECT_ROOT / "schema",
                    reference=alpha_school_reference(),
                    workdays=business_workdays(),
                )

    def test_allows_missing_previous_business_day_when_wave_is_waived(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            processed_dir = Path(tmp)
            pl.DataFrame(
                [
                    {
                        "client_id": "0000000002",
                        "school_id": "1001",
                        "school_name": "ALPHA ELEMENTARY SCHOOL",
                        "first_name": "B",
                        "last_name": "Two",
                        "date_of_birth": date(2012, 2, 2),
                        "rescind_date": None,
                    }
                ]
            ).write_parquet(
                processed_dir / "20260225_suspension_list_elementary.parquet"
            )
            pl.DataFrame(
                [
                    {
                        "client_id": "0000000003",
                        "school_id": "1001",
                        "school_name": "ALPHA ELEMENTARY SCHOOL",
                        "first_name": "C",
                        "last_name": "Three",
                        "date_of_birth": date(2012, 3, 3),
                        "overdue_agents": "MMR",
                    }
                ]
            ).write_parquet(processed_dir / "20260225_overdue_list_pear.parquet")
            pl.DataFrame(
                [
                    {
                        "client_id": "0000000001",
                        "school_id": "1001",
                        "school_name": "ALPHA ELEMENTARY SCHOOL",
                        "first_name": "A",
                        "last_name": "One",
                        "date_of_birth": date(2012, 1, 1),
                        "action_required": "rescind",
                        "action_date": date(2026, 2, 25),
                    }
                ]
            ).write_parquet(processed_dir / "20260225_suspension_vs_overdue.parquet")

            selection = discover_latest_pear_processed_inputs(
                processed_dir=processed_dir,
                run_date="20260225",
            )
            result = derive_pear_state(
                selection=selection,
                schema_root=PROJECT_ROOT / "schema",
                reference=alpha_school_reference(),
                workdays=business_workdays(),
                continuity_waived_waves={"ELEMENTARY1"},
            )

            self.assertEqual(result.prior_suspension_source, "none")
            self.assertIn(
                "continuity bootstrap bypass enabled; missing previous business day",
                "\n".join(result.continuity_warning_messages),
            )

    def test_hard_fails_when_initial_day_suspension_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            processed_dir = Path(tmp)
            pl.DataFrame(
                [
                    {
                        "client_id": "0000000002",
                        "school_id": "1001",
                        "school_name": "ALPHA ELEMENTARY SCHOOL",
                        "first_name": "B",
                        "last_name": "Two",
                        "date_of_birth": date(2012, 2, 2),
                        "rescind_date": None,
                    }
                ]
            ).write_parquet(
                processed_dir / "20260223_suspension_list_elementary.parquet"
            )
            pl.DataFrame(
                [
                    {
                        "client_id": "0000000003",
                        "school_id": "1001",
                        "school_name": "ALPHA ELEMENTARY SCHOOL",
                        "first_name": "C",
                        "last_name": "Three",
                        "date_of_birth": date(2012, 3, 3),
                        "overdue_agents": "MMR",
                    }
                ]
            ).write_parquet(processed_dir / "20260224_overdue_list_pear.parquet")
            pl.DataFrame(
                [
                    {
                        "client_id": "0000000001",
                        "school_id": "1001",
                        "school_name": "ALPHA ELEMENTARY SCHOOL",
                        "first_name": "A",
                        "last_name": "One",
                        "date_of_birth": date(2012, 1, 1),
                        "action_required": "rescind",
                        "action_date": date(2026, 2, 24),
                    }
                ]
            ).write_parquet(processed_dir / "20260224_suspension_vs_overdue.parquet")

            selection = discover_latest_pear_processed_inputs(
                processed_dir=processed_dir,
                run_date="20260224",
            )
            with self.assertRaisesRegex(
                ValidationError,
                "missing current suspension list "
                "20260224_suspension_list_elementary.parquet",
            ):
                derive_pear_state(
                    selection=selection,
                    schema_root=PROJECT_ROOT / "schema",
                    reference=alpha_school_reference(),
                    workdays=business_workdays(),
                )

    def test_warns_before_suspension_start_when_initial_list_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            processed_dir = Path(tmp)
            pl.DataFrame(
                [
                    {
                        "client_id": "0000000002",
                        "school_id": "1001",
                        "school_name": "ALPHA ELEMENTARY SCHOOL",
                        "first_name": "B",
                        "last_name": "Two",
                        "date_of_birth": date(2012, 2, 2),
                        "rescind_date": None,
                    }
                ]
            ).write_parquet(
                processed_dir / "20260220_suspension_list_elementary.parquet"
            )
            pl.DataFrame(
                [
                    {
                        "client_id": "0000000003",
                        "school_id": "1001",
                        "school_name": "ALPHA ELEMENTARY SCHOOL",
                        "first_name": "C",
                        "last_name": "Three",
                        "date_of_birth": date(2012, 3, 3),
                        "overdue_agents": "MMR",
                    }
                ]
            ).write_parquet(processed_dir / "20260220_overdue_list_pear.parquet")
            pl.DataFrame(
                [
                    {
                        "client_id": "0000000001",
                        "school_id": "1001",
                        "school_name": "ALPHA ELEMENTARY SCHOOL",
                        "first_name": "A",
                        "last_name": "One",
                        "date_of_birth": date(2012, 1, 1),
                        "action_required": "delete",
                        "action_date": date(2026, 2, 20),
                    }
                ]
            ).write_parquet(processed_dir / "20260220_suspension_vs_overdue.parquet")

            selection = discover_latest_pear_processed_inputs(
                processed_dir=processed_dir,
                run_date="20260220",
            )
            result = derive_pear_state(
                selection=selection,
                schema_root=PROJECT_ROOT / "schema",
                reference=alpha_school_reference(),
                workdays=business_workdays(),
            )

            self.assertGreaterEqual(len(result.warning_messages), 1)
            self.assertIn(
                "initial suspension list not yet provided",
                "\n".join(result.warning_messages),
            )
            self.assertIn(
                "expected by previous business day before suspension_window_start (20260224)",
                "\n".join(result.warning_messages),
            )
            self.assertIn(
                "previous business day overdue file is unavailable",
                "\n".join(result.warning_messages),
            )
            self.assertEqual(
                result.overdue_day_over_day_summary.get("status"),
                "warning",
            )

    def test_initial_day_does_not_require_two_days_before_suspension_list(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            processed_dir = Path(tmp)
            pl.DataFrame(
                [
                    {
                        "client_id": "0000000001",
                        "school_id": "1001",
                        "school_name": "ALPHA ELEMENTARY SCHOOL",
                        "first_name": "A",
                        "last_name": "One",
                        "date_of_birth": date(2012, 1, 1),
                        "rescind_date": None,
                    }
                ]
            ).write_parquet(
                processed_dir / "20260224_suspension_list_elementary.parquet"
            )
            pl.DataFrame(
                [
                    {
                        "client_id": "0000000003",
                        "school_id": "1001",
                        "school_name": "ALPHA ELEMENTARY SCHOOL",
                        "first_name": "C",
                        "last_name": "Three",
                        "date_of_birth": date(2012, 3, 3),
                        "overdue_agents": "MMR",
                    }
                ]
            ).write_parquet(processed_dir / "20260223_overdue_list_pear.parquet")
            pl.DataFrame(
                [
                    {
                        "client_id": "0000000003",
                        "school_id": "1001",
                        "school_name": "ALPHA ELEMENTARY SCHOOL",
                        "first_name": "C",
                        "last_name": "Three",
                        "date_of_birth": date(2012, 3, 3),
                        "overdue_agents": "MMR",
                    }
                ]
            ).write_parquet(processed_dir / "20260224_overdue_list_pear.parquet")
            pl.DataFrame(
                [
                    {
                        "client_id": "0000000001",
                        "school_id": "1001",
                        "school_name": "ALPHA ELEMENTARY SCHOOL",
                        "first_name": "A",
                        "last_name": "One",
                        "date_of_birth": date(2012, 1, 1),
                        "action_required": "rescind",
                        "action_date": date(2026, 2, 25),
                    }
                ]
            ).write_parquet(processed_dir / "20260224_suspension_vs_overdue.parquet")

            selection = discover_latest_pear_processed_inputs(
                processed_dir=processed_dir,
                run_date="20260224",
            )
            result = derive_pear_state(
                selection=selection,
                schema_root=PROJECT_ROOT / "schema",
                reference=alpha_school_reference(),
                workdays=business_workdays(),
            )

            self.assertEqual(
                result.selection.selected_dates["suspension_active"], "20260224"
            )
            self.assertEqual(result.frames["suspension_active"].height, 1)
            self.assertEqual(result.overdue_day_over_day_summary.get("status"), "pass")

    def test_warns_when_previous_business_day_overdue_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            processed_dir = Path(tmp)
            pl.DataFrame(
                [
                    {
                        "client_id": "0000000002",
                        "school_id": "1001",
                        "school_name": "ALPHA ELEMENTARY SCHOOL",
                        "first_name": "B",
                        "last_name": "Two",
                        "date_of_birth": date(2012, 2, 2),
                        "rescind_date": None,
                    }
                ]
            ).write_parquet(
                processed_dir / "20260224_suspension_list_elementary.parquet"
            )
            pl.DataFrame(
                [
                    {
                        "client_id": "0000000003",
                        "school_id": "1001",
                        "school_name": "ALPHA ELEMENTARY SCHOOL",
                        "first_name": "C",
                        "last_name": "Three",
                        "date_of_birth": date(2012, 3, 3),
                        "overdue_agents": "MMR",
                    }
                ]
            ).write_parquet(processed_dir / "20260224_overdue_list_pear.parquet")
            pl.DataFrame(
                [
                    {
                        "client_id": "0000000001",
                        "school_id": "1001",
                        "school_name": "ALPHA ELEMENTARY SCHOOL",
                        "first_name": "A",
                        "last_name": "One",
                        "date_of_birth": date(2012, 1, 1),
                        "action_required": "delete",
                        "action_date": date(2026, 2, 24),
                    }
                ]
            ).write_parquet(processed_dir / "20260224_suspension_vs_overdue.parquet")

            selection = discover_latest_pear_processed_inputs(
                processed_dir=processed_dir,
                run_date="20260224",
            )
            result = derive_pear_state(
                selection=selection,
                schema_root=PROJECT_ROOT / "schema",
                reference=alpha_school_reference(),
                workdays=business_workdays(),
            )

            self.assertIn(
                "previous business day overdue file is unavailable "
                "(20260223_overdue_list_pear.parquet)",
                "\n".join(result.warning_messages),
            )
            self.assertEqual(
                result.overdue_day_over_day_summary.get("status"),
                "warning",
            )
            self.assertEqual(
                result.overdue_day_over_day_summary.get("introduced_client_count"),
                0,
            )

    def test_warns_when_current_overdue_has_new_clients(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            processed_dir = Path(tmp)
            pl.DataFrame(
                [
                    {
                        "client_id": "0000000001",
                        "school_id": "1001",
                        "school_name": "ALPHA ELEMENTARY SCHOOL",
                        "first_name": "A",
                        "last_name": "One",
                        "date_of_birth": date(2012, 1, 1),
                        "rescind_date": None,
                    }
                ]
            ).write_parquet(
                processed_dir / "20260224_suspension_list_elementary.parquet"
            )
            pl.DataFrame(
                [
                    {
                        "client_id": "0000000001",
                        "school_id": "1001",
                        "school_name": "ALPHA ELEMENTARY SCHOOL",
                        "first_name": "A",
                        "last_name": "One",
                        "date_of_birth": date(2012, 1, 1),
                        "rescind_date": None,
                    }
                ]
            ).write_parquet(
                processed_dir / "20260225_suspension_list_elementary.parquet"
            )
            pl.DataFrame(
                [
                    {
                        "client_id": "0000000001",
                        "school_id": "1001",
                        "school_name": "ALPHA ELEMENTARY SCHOOL",
                        "first_name": "A",
                        "last_name": "One",
                        "date_of_birth": date(2012, 1, 1),
                        "overdue_agents": "MMR",
                    }
                ]
            ).write_parquet(processed_dir / "20260224_overdue_list_pear.parquet")
            pl.DataFrame(
                [
                    {
                        "client_id": "0000000001",
                        "school_id": "1001",
                        "school_name": "ALPHA ELEMENTARY SCHOOL",
                        "first_name": "A",
                        "last_name": "One",
                        "date_of_birth": date(2012, 1, 1),
                        "overdue_agents": "MMR",
                    },
                    {
                        "client_id": "0000000009",
                        "school_id": "1001",
                        "school_name": "ALPHA ELEMENTARY SCHOOL",
                        "first_name": "I",
                        "last_name": "Nine",
                        "date_of_birth": date(2012, 9, 9),
                        "overdue_agents": "TDAP",
                    },
                ]
            ).write_parquet(processed_dir / "20260225_overdue_list_pear.parquet")
            pl.DataFrame(
                [
                    {
                        "client_id": "0000000001",
                        "school_id": "1001",
                        "school_name": "ALPHA ELEMENTARY SCHOOL",
                        "first_name": "A",
                        "last_name": "One",
                        "date_of_birth": date(2012, 1, 1),
                        "action_required": "rescind",
                        "action_date": date(2026, 2, 25),
                    }
                ]
            ).write_parquet(processed_dir / "20260225_suspension_vs_overdue.parquet")

            selection = discover_latest_pear_processed_inputs(
                processed_dir=processed_dir,
                run_date="20260225",
            )
            result = derive_pear_state(
                selection=selection,
                schema_root=PROJECT_ROOT / "schema",
                reference=alpha_school_reference(),
                workdays=business_workdays(),
            )

            warnings = "\n".join(result.warning_messages)
            self.assertIn(
                "current overdue rows are absent from previous business day overdue list",
                warnings,
            )
            self.assertIn("client_id=0000000009 school_id=1001", warnings)
            self.assertEqual(
                result.overdue_day_over_day_summary.get("status"),
                "warning",
            )
            self.assertEqual(
                result.overdue_day_over_day_summary.get("introduced_client_count"),
                1,
            )

    def test_invalid_action_domain_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            processed_dir = Path(tmp)
            pl.DataFrame(
                [
                    {
                        "client_id": "0000000001",
                        "school_id": "1001",
                        "school_name": "ALPHA ELEMENTARY SCHOOL",
                        "first_name": "A",
                        "last_name": "One",
                        "date_of_birth": date(2012, 1, 1),
                        "rescind_date": None,
                    }
                ]
            ).write_parquet(
                processed_dir / "20260224_suspension_list_elementary.parquet"
            )
            pl.DataFrame(
                [
                    {
                        "client_id": "0000000002",
                        "school_id": "3001",
                        "school_name": "BETA SECONDARY SCHOOL",
                        "first_name": "B",
                        "last_name": "Two",
                        "date_of_birth": date(2011, 2, 2),
                        "rescind_date": None,
                    }
                ]
            ).write_parquet(
                processed_dir / "20260224_suspension_list_secondary.parquet"
            )
            pl.DataFrame(
                [
                    {
                        "client_id": "0000000003",
                        "school_id": "1001",
                        "school_name": "ALPHA ELEMENTARY SCHOOL",
                        "first_name": "C",
                        "last_name": "Three",
                        "date_of_birth": date(2013, 3, 3),
                        "overdue_agents": "MMR",
                    }
                ]
            ).write_parquet(processed_dir / "20260224_overdue_list_pear.parquet")
            pl.DataFrame(
                [
                    {
                        "client_id": "0000000004",
                        "school_id": "1001",
                        "school_name": "ALPHA ELEMENTARY SCHOOL",
                        "first_name": "D",
                        "last_name": "Four",
                        "date_of_birth": date(2014, 4, 4),
                        "action_required": "no_action",
                        "action_date": date(2026, 2, 24),
                    }
                ]
            ).write_parquet(processed_dir / "20260224_suspension_vs_overdue.parquet")

            selection = discover_latest_pear_processed_inputs(
                processed_dir=processed_dir,
                run_date="20260224",
            )
            with self.assertRaisesRegex(
                ValidationError, "invalid action_required values"
            ):
                derive_pear_state(
                    selection=selection,
                    schema_root=PROJECT_ROOT / "schema",
                    reference=alpha_beta_reference(),
                )

    def test_write_and_discover_authoritative_baseline_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp)
            suspension_operational = pl.DataFrame(
                [
                    {
                        "client_id": "0000000001",
                        "school_id": "1001",
                        "school_name": "ALPHA ELEMENTARY SCHOOL",
                        "first_name": "A",
                        "last_name": "ONE",
                        "date_of_birth": date(2012, 1, 1),
                        "rescind_date": None,
                        "level": "ELEMENTARY",
                        "wave": "ELEMENTARY1",
                    },
                    {
                        "client_id": "0000000002",
                        "school_id": "3001",
                        "school_name": "BETA SECONDARY SCHOOL",
                        "first_name": "B",
                        "last_name": "TWO",
                        "date_of_birth": date(2011, 2, 2),
                        "rescind_date": date(2026, 2, 24),
                        "level": "SECONDARY",
                        "wave": "SECONDARY1",
                    },
                ]
            )
            written = write_pear_authoritative_suspension_outputs(
                suspension_operational=suspension_operational,
                run_date="20260224",
                output_dir=output_dir,
            )
            self.assertEqual(
                sorted(path.name for path in written),
                [
                    "20260224_pear_suspension_operational_elementary1.parquet",
                    "20260224_pear_suspension_operational_secondary1.parquet",
                ],
            )
            discovered = discover_latest_pear_authoritative_baseline_by_slice(
                output_dir,
                run_date="20260224",
                exact_run_date=True,
            )
            self.assertEqual(set(discovered), {"elementary1", "secondary1"})

    def test_derive_prefers_prior_authoritative_baseline_when_available(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            processed_dir = tmp_path / "processed"
            legacy_baseline_dir = tmp_path / "legacy_baseline"
            processed_dir.mkdir(parents=True, exist_ok=True)
            legacy_baseline_dir.mkdir(parents=True, exist_ok=True)

            pl.DataFrame(
                [
                    {
                        "client_id": "0000000001",
                        "school_id": "1001",
                        "school_name": "ALPHA ELEMENTARY SCHOOL",
                        "first_name": "A",
                        "last_name": "ONE",
                        "date_of_birth": date(2012, 1, 1),
                        "rescind_date": None,
                    }
                ]
            ).write_parquet(
                processed_dir / "20260224_suspension_list_elementary.parquet"
            )
            pl.DataFrame(
                [
                    {
                        "client_id": "0000000002",
                        "school_id": "1001",
                        "school_name": "ALPHA ELEMENTARY SCHOOL",
                        "first_name": "B",
                        "last_name": "TWO",
                        "date_of_birth": date(2012, 2, 2),
                        "rescind_date": None,
                    }
                ]
            ).write_parquet(
                processed_dir / "20260225_suspension_list_elementary.parquet"
            )
            pl.DataFrame(
                [
                    {
                        "client_id": "0000000003",
                        "school_id": "1001",
                        "school_name": "ALPHA ELEMENTARY SCHOOL",
                        "first_name": "C",
                        "last_name": "THREE",
                        "date_of_birth": date(2012, 3, 3),
                        "overdue_agents": "MMR",
                    }
                ]
            ).write_parquet(processed_dir / "20260225_overdue_list_pear.parquet")
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
            ).write_parquet(processed_dir / "20260225_suspension_vs_overdue.parquet")

            pl.DataFrame(
                [
                    {
                        "client_id": "0000000009",
                        "school_id": "1001",
                        "school_name": "ALPHA ELEMENTARY SCHOOL",
                        "first_name": "Z",
                        "last_name": "NINE",
                        "date_of_birth": date(2011, 9, 9),
                        "rescind_date": date(2026, 2, 25),
                        "level": "ELEMENTARY",
                        "wave": "ELEMENTARY1",
                    }
                ]
            ).write_parquet(
                legacy_baseline_dir
                / "20260224_pear_suspension_operational_elementary1.parquet"
            )

            selection = discover_latest_pear_processed_inputs(
                processed_dir=processed_dir,
                run_date="20260225",
            )
            result = derive_pear_state(
                selection=selection,
                schema_root=PROJECT_ROOT / "schema",
                reference=alpha_school_reference(),
                authoritative_dir=legacy_baseline_dir,
                workdays=business_workdays(),
            )
            self.assertEqual(
                result.prior_suspension_source,
                "official_operational_baseline",
            )
            self.assertEqual(result.disappearance_summary["disappeared_count"], 1)
            self.assertEqual(
                result.disappearance_evidence.get_column("client_id").to_list(),
                ["0000000009"],
            )


if __name__ == "__main__":
    unittest.main()
