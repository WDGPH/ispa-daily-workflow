from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from azure.core.exceptions import ResourceNotFoundError

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_ROOT))

from panorama_compliance.io.adls import (  # noqa: E402
    AdlsDestinations,
    AdlsSettings,
    discover_compliance_history_slices_for_date,
    download_latest_compliance_histories,
)


class _FakeFileSystemClient:
    def __init__(
        self,
        *,
        listings: dict[str, list[SimpleNamespace]],
        missing_prefixes: set[str] | None = None,
    ) -> None:
        self._listings = listings
        self._missing_prefixes = missing_prefixes or set()
        self.calls: list[str] = []

    def get_paths(self, *, path: str):  # type: ignore[override]
        self.calls.append(path)
        if path in self._missing_prefixes:
            raise ResourceNotFoundError(message=f"missing: {path}")
        return iter(self._listings.get(path, []))


def _file_entry(path: str) -> SimpleNamespace:
    return SimpleNamespace(name=path, is_directory=False)


class TestAdlsSyncPrefixSelection(unittest.TestCase):
    def test_discover_slices_for_date_uses_processed_prefix_by_default(self) -> None:
        processed_prefix = "Processed/panorama_compliance"
        fake_client = _FakeFileSystemClient(
            listings={
                processed_prefix: [
                    _file_entry(
                        "Processed/panorama_compliance/"
                        "20260213_panorama_secondary1_compliance_history.parquet"
                    ),
                    _file_entry(
                        "Processed/panorama_compliance/"
                        "20260213_panorama_elementary1_compliance_history.parquet"
                    ),
                    _file_entry(
                        "Processed/panorama_compliance/"
                        "20260212_panorama_secondary1_compliance_history.parquet"
                    ),
                    _file_entry("Processed/panorama_compliance/README.txt"),
                ],
            },
        )
        settings = AdlsSettings(
            secrets_path=Path("/tmp"),
            secret_files={},
            destinations=AdlsDestinations(
                landing_prefix="Landing/panorama_compliance",
                processed_prefix=processed_prefix,
            ),
        )

        with patch(
            "panorama_compliance.io.adls.get_file_system_client",
            return_value=fake_client,
        ):
            slices = discover_compliance_history_slices_for_date(
                settings,
                run_date="20260213",
            )

        self.assertEqual(slices, ["elementary1", "secondary1"])
        self.assertEqual(fake_client.calls, [processed_prefix])

    def test_discover_slices_for_date_explicit_prefix_stays_strict(self) -> None:
        explicit_prefix = "Processed/missing_prefix"
        processed_prefix = "Processed/panorama_compliance"
        fake_client = _FakeFileSystemClient(
            listings={
                processed_prefix: [
                    _file_entry(
                        "Processed/panorama_compliance/"
                        "20260213_panorama_secondary1_compliance_history.parquet"
                    )
                ]
            },
            missing_prefixes={explicit_prefix},
        )
        settings = AdlsSettings(
            secrets_path=Path("/tmp"),
            secret_files={},
            destinations=AdlsDestinations(
                landing_prefix="Landing/panorama_compliance",
                processed_prefix=processed_prefix,
            ),
        )

        with patch(
            "panorama_compliance.io.adls.get_file_system_client",
            return_value=fake_client,
        ):
            with self.assertRaises(ResourceNotFoundError):
                discover_compliance_history_slices_for_date(
                    settings,
                    run_date="20260213",
                    prefix=explicit_prefix,
                )

        self.assertEqual(fake_client.calls, [explicit_prefix])

    def test_uses_processed_prefix_by_default(self) -> None:
        processed_prefix = "Processed/panorama_compliance"
        fake_client = _FakeFileSystemClient(
            listings={
                processed_prefix: [
                    _file_entry(
                        "Processed/panorama_compliance/"
                        "20260212_panorama_secondary1_compliance_history.parquet"
                    ),
                    _file_entry(
                        "Processed/panorama_compliance/"
                        "20260210_panorama_secondary1_compliance_history.parquet"
                    ),
                    _file_entry(
                        "Processed/panorama_compliance/"
                        "20260212_panorama_elementary1_compliance_history.parquet"
                    ),
                ],
            },
        )
        settings = AdlsSettings(
            secrets_path=Path("/tmp"),
            secret_files={},
            destinations=AdlsDestinations(
                landing_prefix="Landing/panorama_compliance",
                processed_prefix=processed_prefix,
            ),
        )

        def _fake_download(_client, remote: str, local: Path) -> None:
            local.write_text(remote, encoding="utf-8")

        with tempfile.TemporaryDirectory() as tmp:
            compliance_history_dir = Path(tmp)
            with (
                patch(
                    "panorama_compliance.io.adls.get_file_system_client",
                    return_value=fake_client,
                ),
                patch(
                    "panorama_compliance.io.adls.download_file",
                    side_effect=_fake_download,
                ),
            ):
                downloaded = download_latest_compliance_histories(
                    settings,
                    compliance_history_dir=compliance_history_dir,
                    run_date="20260213",
                    include_run_date=False,
                )

        self.assertEqual(fake_client.calls, [processed_prefix])
        self.assertEqual(
            {path.name for path in downloaded},
            {
                "20260212_panorama_elementary1_compliance_history.parquet",
                "20260212_panorama_secondary1_compliance_history.parquet",
            },
        )

    def test_missing_default_prefix_returns_empty(self) -> None:
        processed_prefix = "Processed/panorama_compliance"
        fake_client = _FakeFileSystemClient(
            listings={},
            missing_prefixes={processed_prefix},
        )
        settings = AdlsSettings(
            secrets_path=Path("/tmp"),
            secret_files={},
            destinations=AdlsDestinations(
                landing_prefix="Landing/panorama_compliance",
                processed_prefix=processed_prefix,
            ),
        )

        with tempfile.TemporaryDirectory() as tmp:
            compliance_history_dir = Path(tmp)
            with patch(
                "panorama_compliance.io.adls.get_file_system_client",
                return_value=fake_client,
            ):
                downloaded = download_latest_compliance_histories(
                    settings,
                    compliance_history_dir=compliance_history_dir,
                    run_date="20260213",
                    include_run_date=False,
                )

        self.assertEqual(downloaded, [])
        self.assertEqual(fake_client.calls, [processed_prefix])

    def test_explicit_prefix_stays_strict_and_raises_on_missing_path(self) -> None:
        explicit_prefix = "Processed/missing_prefix"
        processed_prefix = "Processed/panorama_compliance"
        fake_client = _FakeFileSystemClient(
            listings={
                processed_prefix: [
                    _file_entry(
                        "Processed/panorama_compliance/"
                        "20260212_panorama_secondary1_compliance_history.parquet"
                    )
                ],
            },
            missing_prefixes={explicit_prefix},
        )
        settings = AdlsSettings(
            secrets_path=Path("/tmp"),
            secret_files={},
            destinations=AdlsDestinations(
                landing_prefix="Landing/panorama_compliance",
                processed_prefix=processed_prefix,
            ),
        )

        with tempfile.TemporaryDirectory() as tmp:
            compliance_history_dir = Path(tmp)
            with patch(
                "panorama_compliance.io.adls.get_file_system_client",
                return_value=fake_client,
            ):
                with self.assertRaises(ResourceNotFoundError):
                    download_latest_compliance_histories(
                        settings,
                        compliance_history_dir=compliance_history_dir,
                        run_date="20260213",
                        include_run_date=False,
                        prefix=explicit_prefix,
                    )

        self.assertEqual(fake_client.calls, [explicit_prefix])


if __name__ == "__main__":
    unittest.main()
