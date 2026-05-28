from __future__ import annotations

import pytest

from ispa_daily_workflow.pipeline.delivery_runtime import IOMode


def test_delivery_io_mode_publish() -> None:
    mode = IOMode.for_delivery(dry_run=False, upload=True, download=True)

    assert mode.label == "publish"
    assert mode.read_authoritative
    assert mode.publish
    assert mode.write_local_outputs


def test_delivery_io_mode_read_authoritative_without_publish() -> None:
    mode = IOMode.for_delivery(dry_run=False, upload=False, download=True)

    assert mode.label == "read-authoritative"
    assert mode.read_authoritative
    assert not mode.publish


def test_delivery_io_mode_local_only() -> None:
    mode = IOMode.for_delivery(dry_run=False, upload=False, download=False)

    assert mode.label == "local-only"
    assert not mode.read_authoritative
    assert not mode.publish


def test_delivery_io_mode_dry_run_suppresses_external_state_reads() -> None:
    mode = IOMode.for_delivery(dry_run=True, upload=True, download=True)

    assert mode.label == "dry-run"
    assert mode.dry_run
    assert not mode.read_authoritative
    assert not mode.publish
    assert not mode.write_local_outputs


def test_delivery_io_mode_rejects_upload_without_download() -> None:
    with pytest.raises(ValueError, match="--upload requires --download"):
        IOMode.for_delivery(dry_run=False, upload=True, download=False)
