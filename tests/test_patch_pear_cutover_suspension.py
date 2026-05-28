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

from ispa_daily_workflow.pipeline.ops.patch_pear_cutover_suspension import (
    _build_cutover_patch,
    _resolve_output_dir,
    main,
)


class TestPatchPearCutoverSuspension(unittest.TestCase):
    def test_build_cutover_patch_excludes_only_run_day_pear_only_rescinds(self) -> None:
        suspension_df = pl.DataFrame(
            [
                {
                    "client_id": "1",
                    "school_id": "1001",
                    "rescind_date": None,
                },
                {
                    "client_id": "2",
                    "school_id": "1001",
                    "rescind_date": date(2026, 2, 25),
                },
                {
                    "client_id": "3",
                    "school_id": "1001",
                    "rescind_date": date(2026, 2, 24),
                },
                {
                    "client_id": "4",
                    "school_id": "1001",
                    "rescind_date": date(2026, 2, 25),
                },
            ]
        )
        overdue_df = pl.DataFrame(
            [
                {"client_id": "1", "school_id": "1001"},
                {"client_id": "2", "school_id": "1001"},
            ]
        )

        patched, excluded = _build_cutover_patch(
            suspension_df=suspension_df,
            panorama_overdue_df=overdue_df,
            run_day=date(2026, 2, 25),
        )

        self.assertEqual(excluded.height, 1)
        self.assertEqual(excluded.get_column("client_id").to_list(), ["4"])
        self.assertEqual(patched.height, 3)
        self.assertEqual(
            sorted(patched.get_column("client_id").to_list()),
            ["1", "2", "3"],
        )

    def test_build_cutover_patch_preserves_pear_only_non_run_day_rescinds(self) -> None:
        suspension_df = pl.DataFrame(
            [
                {
                    "client_id": "10",
                    "school_id": "2001",
                    "rescind_date": date(2026, 2, 24),
                },
                {
                    "client_id": "11",
                    "school_id": "2001",
                    "rescind_date": date(2026, 2, 25),
                },
            ]
        )
        overdue_df = pl.DataFrame([{"client_id": "11", "school_id": "2001"}])

        patched, excluded = _build_cutover_patch(
            suspension_df=suspension_df,
            panorama_overdue_df=overdue_df,
            run_day=date(2026, 2, 25),
        )

        self.assertEqual(excluded.height, 0)
        self.assertEqual(patched.height, 2)

    def test_resolve_output_dir_defaults_to_cutover_patch_under_output_root(
        self,
    ) -> None:
        output_root = Path("/tmp/out")
        resolved = _resolve_output_dir(
            requested_output_dir=None,
            output_root=output_root,
        )
        self.assertEqual(resolved, output_root / "cutover_patch")

    def test_dry_run_writes_no_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            output_root = root / "output"
            artifacts_root = root / "artifacts"
            output_root.mkdir(parents=True, exist_ok=True)
            artifacts_root.mkdir(parents=True, exist_ok=True)
            config_path = root / "config.yaml"
            config_path.write_text(
                "\n".join(
                    [
                        "paths:",
                        f'  output_root: "{output_root}"',
                        f'  artifacts_root: "{artifacts_root}"',
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            suspension_path = root / "suspension.parquet"
            overdue_path = root / "overdue.parquet"
            pl.DataFrame(
                {
                    "client_id": ["100", "200"],
                    "school_id": ["1", "1"],
                    "rescind_date": [None, date(2026, 2, 25)],
                }
            ).write_parquet(suspension_path)
            pl.DataFrame(
                {
                    "client_id": ["100"],
                    "school_id": ["1"],
                }
            ).write_parquet(overdue_path)
            exit_code = main(
                [
                    "--run-date",
                    "20260225",
                    "--previous-date",
                    "20260224",
                    "--wave",
                    "ELEMENTARY2",
                    "--config",
                    str(config_path),
                    "--pear-suspension-file",
                    str(suspension_path),
                    "--panorama-overdue-file",
                    str(overdue_path),
                    "--dry-run",
                ]
            )
            self.assertEqual(exit_code, 0)
            cutover_dir = output_root / "cutover_patch"
            self.assertFalse(cutover_dir.exists())
            quality_dir = artifacts_root / "data_quality"
            self.assertFalse(quality_dir.exists())


if __name__ == "__main__":
    unittest.main()
