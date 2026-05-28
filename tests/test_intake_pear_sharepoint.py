from __future__ import annotations

import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_ROOT))

from ispa_daily_workflow.pipeline.intake_pear import (
    _resolve_pear_source_keys,
)


def _config_with_pear_inputs(
    *,
    pear_overdue: str | None,
    pear_suspension_vs_overdue: str | None,
    pear_suspension: str | None,
) -> dict[str, object]:
    return {
        "io": {
            "sharepoint": {
                "secrets_path": "/tmp/secrets",
                "secret_files": {
                    "tenant_id": "tenant",
                    "client_id": "client",
                    "client_secret": "secret",
                },
                "inputs": {
                    "pear_overdue": pear_overdue,
                    "pear_suspension_vs_overdue": pear_suspension_vs_overdue,
                    "pear_suspension": pear_suspension,
                },
                "outputs": {},
            }
        }
    }


class TestIntakePearSharePointSourceKeys(unittest.TestCase):
    def test_uses_all_configured_keys_when_not_requested(self) -> None:
        config = _config_with_pear_inputs(
            pear_overdue="https://example/pear/reports",
            pear_suspension_vs_overdue="https://example/pear/reports",
            pear_suspension="https://example/pear/reports",
        )
        resolved = _resolve_pear_source_keys(config=config, requested_keys=None)
        self.assertEqual(
            resolved,
            [
                "inputs.pear_overdue",
                "inputs.pear_suspension_vs_overdue",
                "inputs.pear_suspension",
            ],
        )

    def test_requested_keys_are_deduplicated_and_preserve_order(self) -> None:
        config = _config_with_pear_inputs(
            pear_overdue="https://example/pear/reports",
            pear_suspension_vs_overdue="https://example/pear/reports",
            pear_suspension=None,
        )
        resolved = _resolve_pear_source_keys(
            config=config,
            requested_keys=[
                "inputs.pear_suspension_vs_overdue",
                "inputs.pear_suspension_vs_overdue",
                "inputs.pear_overdue",
            ],
        )
        self.assertEqual(
            resolved,
            ["inputs.pear_suspension_vs_overdue", "inputs.pear_overdue"],
        )

    def test_requested_key_must_be_configured(self) -> None:
        config = _config_with_pear_inputs(
            pear_overdue="https://example/pear/reports",
            pear_suspension_vs_overdue=None,
            pear_suspension=None,
        )
        with self.assertRaisesRegex(ValueError, "not configured"):
            _resolve_pear_source_keys(
                config=config,
                requested_keys=["inputs.pear_suspension_vs_overdue"],
            )

    def test_requires_at_least_one_configured_source(self) -> None:
        config = _config_with_pear_inputs(
            pear_overdue=None,
            pear_suspension_vs_overdue=None,
            pear_suspension=None,
        )
        with self.assertRaisesRegex(ValueError, "No PEAR SharePoint source keys"):
            _resolve_pear_source_keys(config=config, requested_keys=None)


if __name__ == "__main__":
    unittest.main()
