from __future__ import annotations

import logging
from pathlib import Path

from panorama_compliance.io.adls import (
    AdlsSettings,
    download_files_for_date,
    download_latest_compliance_histories,
    get_file_system_client,
    upload_file,
)
from panorama_compliance.progress import tqdm


def landing_prefix(adls_settings: AdlsSettings, override: str | None) -> str:
    if override:
        return override
    return adls_settings.destinations.landing_prefix


def upload_landing_files(
    adls_settings: AdlsSettings,
    *,
    paths: list[Path],
    prefix: str,
) -> list[str]:
    file_system_client = get_file_system_client(adls_settings)
    uploaded: list[str] = []
    for path in tqdm(sorted(paths), desc="ADLS landing upload", unit="file"):
        remote_path = f"{prefix}/{path.name}"
        logging.debug("Uploading %s -> %s", path, remote_path)
        upload_file(file_system_client, path, remote_path)
        uploaded.append(remote_path)
    if uploaded:
        logging.info(
            "Uploaded %s extracted files to ADLS landing prefix %s",
            len(uploaded),
            prefix,
        )
    return uploaded


def download_landing_files_for_run(
    adls_settings: AdlsSettings,
    *,
    run_date: str,
    output_dir: Path,
    prefix: str,
) -> list[Path]:
    return download_files_for_date(
        adls_settings,
        run_date=run_date,
        output_dir=output_dir,
        prefix=prefix,
    )


def sync_prior_compliance_histories(
    adls_settings: AdlsSettings,
    *,
    compliance_history_dir: Path,
    run_date: str,
) -> list[Path]:
    return download_latest_compliance_histories(
        adls_settings,
        compliance_history_dir=compliance_history_dir,
        run_date=run_date,
        include_run_date=False,
        purge_local_before_sync=True,
    )
