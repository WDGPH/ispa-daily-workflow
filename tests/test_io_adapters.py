from __future__ import annotations

from pathlib import Path

from ispa_daily_workflow.io.adapters import (
    AdlsStateStore,
    LocalInputProvider,
    LocalOutputPublisher,
    LocalStateStore,
    SharePointOutputPublisher,
    load_output_publisher,
    load_state_store,
)


def _adls_config() -> dict[str, object]:
    return {
        "io": {
            "adls": {
                "secrets_path": "/tmp/secrets/adls",
                "secret_files": {
                    "tenant_id": "tenant",
                    "client_id": "client",
                    "client_secret": "secret",
                    "storage_account": "account",
                    "container": "container",
                },
                "destinations": {
                    "landing_prefix": "Landing/current",
                    "processed_prefix": "Processed/current",
                    "pear_landing_prefix": "Landing/pear",
                    "pear_processed_prefix": "Processed/pear",
                },
            }
        }
    }


def _sharepoint_config() -> dict[str, object]:
    return {
        "io": {
            "sharepoint": {
                "secrets_path": "/tmp/secrets/sharepoint",
                "secret_files": {
                    "tenant_id": "tenant",
                    "client_id": "client",
                    "client_secret": "secret",
                },
                "inputs": {},
                "outputs": {
                    "list_difference": "https://example.invalid/list-diff",
                    "action_queue": "https://example.invalid/action-queue",
                },
            }
        }
    }


def test_default_state_store_adapter_is_adls() -> None:
    store = load_state_store(_adls_config())

    assert isinstance(store, AdlsStateStore)
    assert store.name == "adls"


def test_default_output_publisher_adapter_is_sharepoint() -> None:
    publisher = load_output_publisher(_sharepoint_config())

    assert isinstance(publisher, SharePointOutputPublisher)
    assert publisher.name == "sharepoint"


def test_local_state_store_downloads_latest_compliance_history(tmp_path: Path) -> None:
    source = tmp_path / "state"
    target = tmp_path / "out" / "compliance_history"
    source.mkdir()
    older = source / "20260223_panorama_secondary1_compliance_history.parquet"
    latest = source / "20260224_panorama_secondary1_compliance_history.parquet"
    other = source / "20260224_panorama_elementary1_compliance_history.parquet"
    older.write_text("older", encoding="utf-8")
    latest.write_text("latest", encoding="utf-8")
    other.write_text("other", encoding="utf-8")

    store = LocalStateStore(source)
    downloaded = store.download_latest_compliance_histories(
        compliance_history_dir=target,
        run_date="20260224",
        purge_local_before_sync=True,
    )

    assert sorted(path.name for path in downloaded) == [
        "20260224_panorama_elementary1_compliance_history.parquet",
        "20260224_panorama_secondary1_compliance_history.parquet",
    ]
    assert (target / latest.name).read_text(encoding="utf-8") == "latest"
    assert store.discover_compliance_history_slices_for_date(run_date="20260224") == [
        "elementary1",
        "secondary1",
    ]


def test_local_input_provider_fetches_files(tmp_path: Path) -> None:
    source = tmp_path / "inputs"
    target = tmp_path / "scratch"
    source.mkdir()
    (source / "pear.xlsx").write_text("workbook", encoding="utf-8")
    (source / "notes.txt").write_text("ignored", encoding="utf-8")

    provider = LocalInputProvider(source)
    fetched = provider.fetch_files(
        destination_keys=["inputs.pear_overdue"],
        output_dir=target,
        overwrite=True,
    )

    assert fetched == [target / "pear.xlsx"]
    assert (target / "pear.xlsx").read_text(encoding="utf-8") == "workbook"


def test_local_output_publisher_copies_by_destination_key(tmp_path: Path) -> None:
    source = tmp_path / "out.xlsx"
    source.write_text("output", encoding="utf-8")
    publisher = LocalOutputPublisher(tmp_path / "published")

    published = publisher.publish_files(
        destination_key="outputs.action_queue",
        paths=[source],
        overwrite=True,
    )

    copied = tmp_path / "published" / "outputs" / "action_queue" / "out.xlsx"
    assert published == [str(copied)]
    assert copied.read_text(encoding="utf-8") == "output"


def test_local_state_store_selected_from_config(tmp_path: Path) -> None:
    config = {
        "io": {
            "state_store": {
                "kind": "local",
                "root": str(tmp_path / "state"),
            }
        }
    }

    store = load_state_store(config)

    assert isinstance(store, LocalStateStore)
    assert store.root == tmp_path / "state"
