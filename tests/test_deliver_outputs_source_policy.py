from __future__ import annotations

import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_ROOT))

from ispa_daily_workflow.pipeline.deliver_outputs import (
    _delivery_io_mode,
    _load_delivery_adapters,
    _parse_args,
)


class TestDeliverOutputsSourcePolicy(unittest.TestCase):
    def test_parse_requires_source(self) -> None:
        with self.assertRaises(SystemExit):
            _parse_args(
                [
                    "sharepoint.overdue.pdf",
                    "--run-date",
                    "20260224",
                    "--wave",
                    "ALL",
                ]
            )

    def test_parse_rejects_pear_for_panorama_only_output(self) -> None:
        with self.assertRaises(SystemExit):
            _parse_args(
                [
                    "sharepoint.panorama.diff.xlsx",
                    "--source",
                    "pear",
                    "--run-date",
                    "20260224",
                    "--wave",
                    "ALL",
                ]
            )

    def test_parse_rejects_panorama_for_pear_only_output(self) -> None:
        with self.assertRaises(SystemExit):
            _parse_args(
                [
                    "sharepoint.action_queue.xlsx",
                    "--source",
                    "panorama",
                    "--run-date",
                    "20260224",
                    "--wave",
                    "ALL",
                ]
            )

    def test_parse_accepts_pear_pdf_output(self) -> None:
        args = _parse_args(
            [
                "sharepoint.overdue.pdf",
                "--source",
                "pear",
                "--run-date",
                "20260224",
                "--wave",
                "ALL",
            ]
        )
        self.assertEqual(args.source, "pear")

    def test_parse_accepts_panorama_pdf_output(self) -> None:
        args = _parse_args(
            [
                "sharepoint.suspension.pdf",
                "--source",
                "panorama",
                "--run-date",
                "20260224",
                "--wave",
                "ALL",
            ]
        )
        self.assertEqual(args.source, "panorama")

    def test_parse_defaults_enable_upload_and_download(self) -> None:
        args = _parse_args(
            [
                "sharepoint.overdue.pdf",
                "--source",
                "panorama",
                "--run-date",
                "20260224",
                "--wave",
                "ALL",
            ]
        )
        self.assertTrue(args.upload)
        self.assertTrue(args.download)

    def test_parse_rejects_upload_without_download(self) -> None:
        with self.assertRaises(SystemExit):
            _parse_args(
                [
                    "sharepoint.overdue.pdf",
                    "--source",
                    "panorama",
                    "--run-date",
                    "20260224",
                    "--wave",
                    "ALL",
                    "--upload",
                    "--no-download",
                ]
            )

    def test_parse_accepts_no_upload_no_download(self) -> None:
        args = _parse_args(
            [
                "sharepoint.overdue.pdf",
                "--source",
                "panorama",
                "--run-date",
                "20260224",
                "--wave",
                "ALL",
                "--no-upload",
                "--no-download",
            ]
        )
        self.assertFalse(args.upload)
        self.assertFalse(args.download)
        self.assertEqual(_delivery_io_mode(args).label, "local-only")

    def test_local_only_mode_does_not_require_external_adapter_config(self) -> None:
        args = _parse_args(
            [
                "sharepoint.overdue.pdf",
                "--source",
                "panorama",
                "--run-date",
                "20260224",
                "--wave",
                "ALL",
                "--no-upload",
                "--no-download",
            ]
        )

        state_store, output_publisher, sharepoint_settings = _load_delivery_adapters(
            config={},
            io_mode=_delivery_io_mode(args),
            needs_sharepoint_cleanup=False,
        )

        self.assertIsNone(state_store)
        self.assertIsNone(output_publisher)
        self.assertIsNone(sharepoint_settings)

    def test_parse_rejects_removed_local_only_flag(self) -> None:
        with self.assertRaises(SystemExit):
            _parse_args(
                [
                    "sharepoint.overdue.pdf",
                    "--source",
                    "panorama",
                    "--run-date",
                    "20260224",
                    "--wave",
                    "ALL",
                    "--local-only",
                ]
            )

    def test_parse_rejects_cleanup_without_upload(self) -> None:
        with self.assertRaises(SystemExit):
            _parse_args(
                [
                    "sharepoint.suspension.pdf",
                    "--source",
                    "panorama",
                    "--run-date",
                    "20260224",
                    "--wave",
                    "ALL",
                    "--no-upload",
                    "--cleanup-sharepoint-pdfs",
                ]
            )

    def test_parse_allows_cleanup_without_upload_in_dry_run(self) -> None:
        args = _parse_args(
            [
                "sharepoint.suspension.pdf",
                "--source",
                "panorama",
                "--run-date",
                "20260224",
                "--wave",
                "ALL",
                "--no-upload",
                "--cleanup-sharepoint-pdfs",
                "--dry-run",
            ]
        )
        self.assertFalse(args.upload)
        self.assertTrue(args.dry_run)

    def test_parse_accepts_pear_suspension_override(self) -> None:
        args = _parse_args(
            [
                "sharepoint.suspension.pdf",
                "--source",
                "pear",
                "--run-date",
                "20260225",
                "--wave",
                "ELEMENTARY1",
                "--pear-suspension-file",
                "output/pear_state/patch.parquet",
            ]
        )
        self.assertEqual(args.source, "pear")
        self.assertEqual(
            str(args.pear_suspension_file),
            "output/pear_state/patch.parquet",
        )

    def test_parse_rejects_pear_suspension_override_on_wrong_output(self) -> None:
        with self.assertRaises(SystemExit):
            _parse_args(
                [
                    "sharepoint.overdue.pdf",
                    "--source",
                    "pear",
                    "--run-date",
                    "20260225",
                    "--wave",
                    "ELEMENTARY1",
                    "--pear-suspension-file",
                    "output/pear_state/patch.parquet",
                ]
            )

    def test_parse_accepts_scoped_continuity_bootstrap_bypass(self) -> None:
        args = _parse_args(
            [
                "sharepoint.suspension.pdf",
                "--source",
                "pear",
                "--run-date",
                "20260224",
                "--wave",
                "SECONDARY1",
                "--no-upload",
                "--allow-missing-prior-suspension-continuity",
            ]
        )
        self.assertTrue(args.allow_missing_prior_suspension_continuity)
        self.assertFalse(args.upload)

    def test_parse_rejects_continuity_bootstrap_bypass_for_all_scope(self) -> None:
        with self.assertRaises(SystemExit):
            _parse_args(
                [
                    "sharepoint.suspension.pdf",
                    "--source",
                    "pear",
                    "--run-date",
                    "20260224",
                    "--wave",
                    "ALL",
                    "--no-upload",
                    "--allow-missing-prior-suspension-continuity",
                ]
            )

    def test_parse_rejects_continuity_bootstrap_bypass_with_upload(self) -> None:
        with self.assertRaises(SystemExit):
            _parse_args(
                [
                    "sharepoint.suspension.pdf",
                    "--source",
                    "pear",
                    "--run-date",
                    "20260224",
                    "--wave",
                    "SECONDARY1",
                    "--allow-missing-prior-suspension-continuity",
                ]
            )


if __name__ == "__main__":
    unittest.main()
