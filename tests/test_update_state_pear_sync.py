from __future__ import annotations

import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_ROOT))

from panorama_compliance.pipeline.update_state import (  # noqa: E402
    _build_pear_intake_command,
    _build_pear_state_command,
    _parse_args,
)


class TestUpdateStatePearSync(unittest.TestCase):
    def test_parse_requires_source(self) -> None:
        with self.assertRaises(SystemExit):
            _parse_args([])

    def test_parse_rejects_panorama_flags_for_pear_source(self) -> None:
        with self.assertRaises(SystemExit):
            _parse_args(["--source", "pear", "--wave", "ALL"])
        with self.assertRaises(SystemExit):
            _parse_args(["--source", "pear", "--init-compliance-history"])
        with self.assertRaises(SystemExit):
            _parse_args(["--source", "pear", "--allow-new-client-ids"])

    def test_parse_rejects_pear_flags_for_panorama_source(self) -> None:
        with self.assertRaises(SystemExit):
            _parse_args(
                [
                    "--source",
                    "panorama",
                    "--sharepoint-source-key",
                    "inputs.pear_overdue",
                ]
            )
        with self.assertRaises(SystemExit):
            _parse_args(["--source", "panorama", "--input-dir", "/tmp/pear-input"])
        with self.assertRaises(SystemExit):
            _parse_args(["--source", "panorama", "--derive-state"])
        with self.assertRaises(SystemExit):
            _parse_args(
                [
                    "--source",
                    "panorama",
                    "--authoritative-output-dir",
                    "/tmp/pear-authoritative",
                ]
            )

    def test_parse_accepts_authoritative_output_dir_for_pear(self) -> None:
        args = _parse_args(
            [
                "--source",
                "pear",
                "--authoritative-output-dir",
                "/tmp/pear-authoritative",
            ]
        )
        self.assertEqual(str(args.authoritative_output_dir), "/tmp/pear-authoritative")

    def test_build_pear_intake_command_includes_requested_source_keys(self) -> None:
        command = _build_pear_intake_command(
            config_path=Path("profile/config.yaml"),
            input_dir=Path("/tmp/pear/input"),
            landing_output_dir=Path("/tmp/pear/landing"),
            processed_output_dir=Path("/tmp/pear/processed"),
            sharepoint_source_keys=[
                "inputs.pear_suspension_vs_overdue",
                "inputs.pear_overdue",
            ],
            download_from_sharepoint=True,
            upload_to_adls=True,
            landing_only=True,
            processed_only=False,
            verbose=True,
        )

        self.assertEqual(command[0], sys.executable)
        self.assertIn("--download-from-sharepoint", command)
        self.assertIn("--upload-to-adls", command)
        self.assertIn("--landing-only", command)
        self.assertNotIn("--processed-only", command)
        self.assertEqual(command.count("--sharepoint-source-key"), 2)
        key_values = [
            command[index + 1]
            for index, token in enumerate(command)
            if token == "--sharepoint-source-key"
        ]
        self.assertEqual(
            key_values,
            [
                "inputs.pear_suspension_vs_overdue",
                "inputs.pear_overdue",
            ],
        )
        self.assertEqual(command[-1], "--verbose")

    def test_build_pear_processed_only_command(self) -> None:
        command = _build_pear_intake_command(
            config_path=Path("profile/config.yaml"),
            input_dir=Path("/tmp/pear/landing"),
            landing_output_dir=Path("/tmp/pear/landing"),
            processed_output_dir=Path("/tmp/pear/processed"),
            sharepoint_source_keys=[],
            download_from_sharepoint=False,
            upload_to_adls=True,
            landing_only=False,
            processed_only=True,
            verbose=False,
        )

        self.assertNotIn("--download-from-sharepoint", command)
        self.assertIn("--upload-to-adls", command)
        self.assertNotIn("--landing-only", command)
        self.assertIn("--processed-only", command)
        self.assertEqual(command.count("--sharepoint-source-key"), 0)

    def test_build_pear_state_command(self) -> None:
        command = _build_pear_state_command(
            config_path=Path("profile/config.yaml"),
            run_date="20260224",
            processed_dir=Path("/tmp/pear/processed"),
            output_dir=Path("/tmp/pear/state"),
            authoritative_output_dir=Path("/tmp/pear/authoritative"),
            verbose=False,
        )

        self.assertEqual(command[0], sys.executable)
        self.assertIn("scripts/derive_pear_state.py", command[1])
        self.assertIn("--run-date", command)
        self.assertIn("20260224", command)
        self.assertIn("--processed-dir", command)
        self.assertIn("/tmp/pear/processed", command)
        self.assertIn("--output-dir", command)
        self.assertIn("/tmp/pear/state", command)
        self.assertIn("--authoritative-output-dir", command)
        self.assertIn("/tmp/pear/authoritative", command)


if __name__ == "__main__":
    unittest.main()
