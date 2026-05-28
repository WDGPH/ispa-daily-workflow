from __future__ import annotations

import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_ROOT))

from panorama_compliance.config import require_config_value  # noqa: E402
from panorama_compliance.io.adls import load_adls_settings  # noqa: E402
from panorama_compliance.io.sharepoint_settings import (  # noqa: E402
    load_sharepoint_settings,
)


class TestStrictConfigLoading(unittest.TestCase):
    def test_require_config_value_missing_key_raises(self) -> None:
        with self.assertRaisesRegex(ValueError, "paths.output_root"):
            require_config_value({}, "output_root", label="paths.output_root")

    def test_load_adls_settings_requires_processed_prefix(self) -> None:
        config = {
            "io": {
                "adls": {
                    "secrets_path": "/mnt/secrets-store/adls",
                    "secret_files": {
                        "tenant_id": "tenant",
                        "client_id": "client",
                        "client_secret": "secret",
                        "storage_account": "account",
                        "container": "container",
                    },
                    "destinations": {
                        "landing_prefix": "Landing/panorama_compliance",
                    },
                }
            }
        }

        with self.assertRaisesRegex(
            ValueError,
            "io.adls.destinations.processed_prefix",
        ):
            load_adls_settings(config)

    def test_load_sharepoint_settings_requires_secret_files(self) -> None:
        config = {
            "io": {
                "sharepoint": {
                    "secrets_path": "/mnt/secrets-store/sharepoint",
                    "inputs": {},
                    "outputs": {},
                    "secret_files": {
                        "tenant_id": "tenant",
                        "client_id": "client",
                    },
                }
            }
        }

        with self.assertRaisesRegex(
            ValueError,
            "io.sharepoint.secret_files.client_secret",
        ):
            load_sharepoint_settings(config)

    def test_load_adls_settings_accepts_optional_pear_prefixes(self) -> None:
        config = {
            "io": {
                "adls": {
                    "secrets_path": "/mnt/secrets-store/adls",
                    "secret_files": {
                        "tenant_id": "tenant",
                        "client_id": "client",
                        "client_secret": "secret",
                        "storage_account": "account",
                        "container": "container",
                    },
                    "destinations": {
                        "landing_prefix": "Landing/panorama_compliance",
                        "processed_prefix": "Processed/panorama_compliance",
                        "pear_landing_prefix": "Landing/pear_compliance",
                        "pear_processed_prefix": "Processed/pear_compliance",
                    },
                }
            }
        }

        settings = load_adls_settings(config)
        self.assertEqual(
            settings.destinations.pear_landing_prefix, "Landing/pear_compliance"
        )
        self.assertEqual(
            settings.destinations.pear_processed_prefix, "Processed/pear_compliance"
        )

    def test_load_sharepoint_settings_accepts_optional_pear_inputs(self) -> None:
        config = {
            "io": {
                "sharepoint": {
                    "secrets_path": "/mnt/secrets-store/sharepoint",
                    "secret_files": {
                        "tenant_id": "tenant",
                        "client_id": "client",
                        "client_secret": "secret",
                    },
                    "inputs": {
                        "pear_overdue": "https://example.com/pear/overdue",
                        "pear_suspension_vs_overdue": "https://example.com/pear/list",
                        "pear_suspension": "https://example.com/pear/suspension",
                    },
                    "outputs": {},
                }
            }
        }

        settings = load_sharepoint_settings(config)
        self.assertEqual(
            settings.inputs.pear_overdue,
            "https://example.com/pear/overdue",
        )
        self.assertEqual(
            settings.inputs.pear_suspension_vs_overdue,
            "https://example.com/pear/list",
        )
        self.assertEqual(
            settings.inputs.pear_suspension,
            "https://example.com/pear/suspension",
        )


if __name__ == "__main__":
    unittest.main()
