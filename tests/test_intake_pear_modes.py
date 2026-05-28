from __future__ import annotations

import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_ROOT))

from panorama_compliance.pipeline.intake_pear import _parse_args  # noqa: E402


class TestIntakePearModes(unittest.TestCase):
    def test_parse_rejects_conflicting_mode_flags(self) -> None:
        with self.assertRaises(SystemExit):
            _parse_args(["--landing-only", "--processed-only"])

    def test_parse_rejects_processed_only_with_sharepoint_download(self) -> None:
        with self.assertRaises(SystemExit):
            _parse_args(["--processed-only", "--download-from-sharepoint"])

    def test_landing_only_disables_processed_writer(self) -> None:
        args = _parse_args(["--landing-only"])
        self.assertTrue(args.landing_only)
        self.assertFalse(args.write_processed)
        self.assertTrue(args.write_landing)

    def test_processed_only_disables_landing_writer(self) -> None:
        args = _parse_args(["--processed-only"])
        self.assertTrue(args.processed_only)
        self.assertFalse(args.write_landing)
        self.assertTrue(args.write_processed)


if __name__ == "__main__":
    unittest.main()
