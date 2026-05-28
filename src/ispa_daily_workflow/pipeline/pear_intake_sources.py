from __future__ import annotations

import logging
from pathlib import Path

from ispa_daily_workflow.config import ensure_dir
from ispa_daily_workflow.io.adapters import (
    InputProvider,
    SharePointInputProvider,
)
from ispa_daily_workflow.io.sharepoint_settings import (
    SharePointSettings,
    load_sharepoint_settings,
)

_PEAR_SHAREPOINT_SOURCE_KEYS = (
    "inputs.pear_overdue",
    "inputs.pear_suspension_vs_overdue",
    "inputs.pear_suspension",
)


def _configured_pear_source_keys(config: dict) -> list[str]:
    sharepoint_settings = load_sharepoint_settings(config)
    keys: list[str] = []
    if sharepoint_settings.inputs.pear_overdue:
        keys.append("inputs.pear_overdue")
    if sharepoint_settings.inputs.pear_suspension_vs_overdue:
        keys.append("inputs.pear_suspension_vs_overdue")
    if sharepoint_settings.inputs.pear_suspension:
        keys.append("inputs.pear_suspension")
    return keys


def _resolve_pear_source_keys(
    *,
    config: dict,
    requested_keys: list[str] | None,
) -> list[str]:
    configured_keys = _configured_pear_source_keys(config)
    if not configured_keys:
        raise ValueError(
            "No PEAR SharePoint source keys are configured under "
            "io.sharepoint.inputs.{pear_overdue,pear_suspension_vs_overdue,pear_suspension}"
        )

    if not requested_keys:
        return configured_keys

    selected: list[str] = []
    for key in requested_keys:
        if key not in selected:
            selected.append(key)

    missing = [key for key in selected if key not in configured_keys]
    if missing:
        raise ValueError(
            "Requested --sharepoint-source-key values are not configured: "
            + ", ".join(missing)
        )
    return selected


def _download_sharepoint_sources(
    *,
    sharepoint_settings: SharePointSettings | None = None,
    input_provider: InputProvider | None = None,
    source_keys: list[str],
    input_dir: Path,
    overwrite: bool,
) -> list[Path]:
    ensure_dir(input_dir)
    provider = input_provider
    if provider is None:
        if sharepoint_settings is None:
            raise ValueError("sharepoint_settings is required without input_provider")
        provider = SharePointInputProvider(sharepoint_settings)
    logging.debug(
        "Fetching PEAR source workbook(s) with %s input provider", provider.name
    )
    return provider.fetch_files(
        destination_keys=source_keys,
        output_dir=input_dir,
        overwrite=overwrite,
        suffix=".xlsx",
    )
