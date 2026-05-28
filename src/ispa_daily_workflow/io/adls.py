from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path

from azure.core.exceptions import ResourceExistsError, ResourceNotFoundError
from azure.identity import ClientSecretCredential
from azure.storage.filedatalake import DataLakeServiceClient, FileSystemClient

from ispa_daily_workflow.config import (
    get_io_config,
    require_config_mapping,
    require_config_value,
)
from ispa_daily_workflow.progress import tqdm

COMPLIANCE_HISTORY_FILENAME_PATTERN = re.compile(
    r"(?P<date>\d{8})_panorama_(?P<slice>.+)_compliance_history\.(?P<ext>parquet)$"
)
LANDING_CANONICAL_FILENAME_PATTERN = re.compile(
    r"^\d{8}_panorama_compliance_.+\.xlsx$",
    re.IGNORECASE,
)
PEAR_LANDING_CANONICAL_FILENAME_PATTERN = re.compile(
    r"^\d{8}_(?:overdue_list_pear|suspension_vs_overdue|suspension_list_(?:elementary|secondary))\.xlsx$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class AdlsDestinations:
    landing_prefix: str
    processed_prefix: str
    pear_landing_prefix: str | None = None
    pear_processed_prefix: str | None = None


@dataclass(frozen=True)
class AdlsSettings:
    secrets_path: Path
    secret_files: dict[str, str]
    destinations: AdlsDestinations


def load_adls_settings(config: dict) -> AdlsSettings:
    io_config = get_io_config(config)
    adls = require_config_mapping(io_config, "adls", label="io.adls")
    destinations_cfg = require_config_mapping(
        adls,
        "destinations",
        label="io.adls.destinations",
    )
    secret_files_cfg = require_config_mapping(
        adls,
        "secret_files",
        label="io.adls.secret_files",
    )
    secret_files: dict[str, str] = {}
    for key in (
        "tenant_id",
        "client_id",
        "client_secret",
        "storage_account",
        "container",
    ):
        secret_files[key] = str(
            require_config_value(
                secret_files_cfg,
                key,
                label=f"io.adls.secret_files.{key}",
            )
        )

    def _optional_prefix(key: str) -> str | None:
        raw = destinations_cfg.get(key)
        if raw is None:
            return None
        value = str(raw).strip()
        if not value:
            raise ValueError(
                f"Config value cannot be empty: io.adls.destinations.{key}. "
                "Update profile/config.yaml."
            )
        return value

    return AdlsSettings(
        secrets_path=Path(
            str(
                require_config_value(
                    adls,
                    "secrets_path",
                    label="io.adls.secrets_path",
                )
            )
        ),
        secret_files=secret_files,
        destinations=AdlsDestinations(
            landing_prefix=str(
                require_config_value(
                    destinations_cfg,
                    "landing_prefix",
                    label="io.adls.destinations.landing_prefix",
                )
            ),
            processed_prefix=str(
                require_config_value(
                    destinations_cfg,
                    "processed_prefix",
                    label="io.adls.destinations.processed_prefix",
                )
            ),
            pear_landing_prefix=_optional_prefix("pear_landing_prefix"),
            pear_processed_prefix=_optional_prefix("pear_processed_prefix"),
        ),
    )


def _read_secret(settings: AdlsSettings, key: str) -> str:
    filename = settings.secret_files.get(key)
    if not filename:
        raise KeyError(f"ADLS secret_files is missing key: {key}")
    return (settings.secrets_path / filename).read_text(encoding="utf-8").strip()


def get_datalake_service_client(settings: AdlsSettings) -> DataLakeServiceClient:
    tenant_id = _read_secret(settings, "tenant_id")
    client_id = _read_secret(settings, "client_id")
    client_secret = _read_secret(settings, "client_secret")
    storage_account = _read_secret(settings, "storage_account")

    credential = ClientSecretCredential(
        tenant_id=tenant_id,
        client_id=client_id,
        client_secret=client_secret,
    )
    account_url = f"https://{storage_account}.dfs.core.windows.net"
    return DataLakeServiceClient(account_url=account_url, credential=credential)


def get_file_system_client(settings: AdlsSettings) -> FileSystemClient:
    service_client = get_datalake_service_client(settings)
    container = _read_secret(settings, "container")
    return service_client.get_file_system_client(container)


def _relative_depth(remote_path: str, prefix: str) -> int:
    normalized_prefix = prefix.strip("/")
    normalized_remote = remote_path.strip("/")
    if normalized_remote == normalized_prefix:
        return 0
    if normalized_remote.startswith(f"{normalized_prefix}/"):
        relative = normalized_remote[len(normalized_prefix) + 1 :]
    else:
        relative = normalized_remote
    return relative.count("/")


def _prefer_remote_path(candidate: str, existing: str, *, prefix: str) -> bool:
    candidate_depth = _relative_depth(candidate, prefix)
    existing_depth = _relative_depth(existing, prefix)
    if candidate_depth != existing_depth:
        return candidate_depth < existing_depth
    return candidate < existing


def list_files_for_date(
    file_system_client: FileSystemClient,
    prefix: str,
    run_date: str,
    *,
    filename_pattern: re.Pattern[str] | None = LANDING_CANONICAL_FILENAME_PATTERN,
) -> list[str]:
    by_name: dict[str, str] = {}
    for entry in file_system_client.get_paths(path=prefix):
        if entry.is_directory:
            continue
        leaf_name = Path(entry.name).name
        if not leaf_name.startswith(f"{run_date}_"):
            continue
        # Landing downloads are strict by default; callers can override patterning.
        if filename_pattern is not None and not filename_pattern.match(leaf_name):
            continue
        existing = by_name.get(leaf_name)
        if existing is None or _prefer_remote_path(
            entry.name,
            existing,
            prefix=prefix,
        ):
            by_name[leaf_name] = entry.name
    return sorted(by_name.values())


def download_file(
    file_system_client: FileSystemClient, remote_path: str, local_path: Path
) -> None:
    local_path.parent.mkdir(parents=True, exist_ok=True)
    client = file_system_client.get_file_client(remote_path)
    download = client.download_file()
    local_path.write_bytes(download.readall())


def download_files_for_date(
    settings: AdlsSettings,
    *,
    run_date: str,
    output_dir: Path,
    prefix: str | None = None,
    filename_pattern: re.Pattern[str] | None = LANDING_CANONICAL_FILENAME_PATTERN,
) -> list[Path]:
    file_system_client = get_file_system_client(settings)
    remote_prefix = prefix or settings.destinations.landing_prefix
    remote_files = list_files_for_date(
        file_system_client,
        remote_prefix,
        run_date,
        filename_pattern=filename_pattern,
    )
    if remote_files:
        logging.debug(
            "Downloading %s files from ADLS prefix %s for run_date=%s",
            len(remote_files),
            remote_prefix,
            run_date,
        )
    else:
        logging.debug(
            "No files found in ADLS prefix %s for run_date=%s",
            remote_prefix,
            run_date,
        )
    downloaded: list[Path] = []
    for remote in tqdm(remote_files, desc="ADLS download", unit="file"):
        target = output_dir / Path(remote).name
        logging.debug("Downloading %s -> %s", remote, target)
        download_file(file_system_client, remote, target)
        downloaded.append(target)
    if downloaded:
        logging.debug("Downloaded %s files to %s", len(downloaded), output_dir)
    return downloaded


def _ensure_remote_directory(
    file_system_client: FileSystemClient, remote_path: str
) -> None:
    parent = "/".join(remote_path.split("/")[:-1])
    if not parent:
        return
    directory_client = file_system_client.get_directory_client(parent)
    try:
        directory_client.create_directory()
    except ResourceExistsError:
        return


def upload_file(
    file_system_client: FileSystemClient, local_path: Path, remote_path: str
) -> None:
    _ensure_remote_directory(file_system_client, remote_path)
    client = file_system_client.get_file_client(remote_path)
    client.upload_data(local_path.read_bytes(), overwrite=True)


def upload_paths(
    settings: AdlsSettings,
    *,
    paths: list[Path],
    prefix: str | None = None,
) -> list[str]:
    file_system_client = get_file_system_client(settings)
    remote_prefix = prefix or settings.destinations.processed_prefix
    unique_paths = sorted(set(paths))
    if unique_paths:
        logging.debug(
            "Uploading %s files to ADLS prefix %s",
            len(unique_paths),
            remote_prefix,
        )
    uploaded: list[str] = []
    for path in tqdm(unique_paths, desc="ADLS upload", unit="file"):
        remote = f"{remote_prefix}/{path.name}"
        logging.debug("Uploading %s -> %s", path, remote)
        upload_file(file_system_client, path, remote)
        uploaded.append(remote)
    if uploaded:
        logging.debug(
            "Uploaded %s files to ADLS prefix %s", len(uploaded), remote_prefix
        )
    return uploaded


def discover_run_outputs(output_dir: Path, run_date: str) -> list[Path]:
    patterns = [
        f"{run_date}_panorama_*_noncompliant.parquet",
        f"{run_date}_*_panorama_*_became_compliant.parquet",
        f"{run_date}_panorama_*_compliance_history.parquet",
    ]
    paths: list[Path] = []
    for pattern in patterns:
        paths.extend(output_dir.glob(pattern))
    return sorted(set(paths))


def _purge_local_compliance_history_snapshots(compliance_history_dir: Path) -> int:
    if not compliance_history_dir.exists():
        return 0
    removed = 0
    for path in compliance_history_dir.glob("*_panorama_*_compliance_history.parquet"):
        if not path.is_file():
            continue
        path.unlink()
        removed += 1
    return removed


def discover_compliance_history_slices_for_date(
    settings: AdlsSettings,
    *,
    run_date: str,
    prefix: str | None = None,
) -> list[str]:
    file_system_client = get_file_system_client(settings)
    remote_prefix = prefix or settings.destinations.processed_prefix
    slices: set[str] = set()
    try:
        entries = file_system_client.get_paths(path=remote_prefix)
        for entry in entries:
            if entry.is_directory:
                continue
            name = Path(entry.name).name
            match = COMPLIANCE_HISTORY_FILENAME_PATTERN.match(name)
            if not match:
                continue
            date_token = match.group("date")
            if date_token != run_date:
                continue
            slice_token = match.group("slice")
            slices.add(slice_token)
    except ResourceNotFoundError:
        if prefix is not None:
            raise
        logging.warning(
            "ADLS prefix %s does not exist while checking compliance_history coverage for run_date=%s; treating as empty source",
            remote_prefix,
            run_date,
        )
        return []

    sorted_slices = sorted(slices)
    if sorted_slices:
        logging.debug(
            "Discovered %s compliance_history slice(s) in ADLS prefix %s for run_date=%s: %s",
            len(sorted_slices),
            remote_prefix,
            run_date,
            ", ".join(sorted_slices),
        )
    else:
        logging.debug(
            "No compliance_history snapshots found in ADLS prefix %s for run_date=%s",
            remote_prefix,
            run_date,
        )
    return sorted_slices


def download_latest_compliance_histories(
    settings: AdlsSettings,
    *,
    compliance_history_dir: Path,
    run_date: str | None = None,
    include_run_date: bool = True,
    purge_local_before_sync: bool = False,
    prefix: str | None = None,
) -> list[Path]:
    file_system_client = get_file_system_client(settings)
    remote_prefix = prefix or settings.destinations.processed_prefix
    latest: dict[str, tuple[str, str]] = {}
    try:
        entries = file_system_client.get_paths(path=remote_prefix)
        for entry in entries:
            if entry.is_directory:
                continue
            name = Path(entry.name).name
            match = COMPLIANCE_HISTORY_FILENAME_PATTERN.match(name)
            if not match:
                continue
            date_token = match.group("date")
            if run_date is not None:
                if include_run_date:
                    if date_token > run_date:
                        continue
                elif date_token >= run_date:
                    continue
            slice_token = match.group("slice")
            existing = latest.get(slice_token)
            if existing is None:
                latest[slice_token] = (date_token, entry.name)
                continue
            existing_date, _ = existing
            if date_token > existing_date:
                latest[slice_token] = (date_token, entry.name)
                continue
    except ResourceNotFoundError:
        if prefix is not None:
            raise
        logging.warning(
            "ADLS prefix %s does not exist while syncing compliance_history snapshots; treating as empty sync source",
            remote_prefix,
        )
    compliance_history_dir.mkdir(parents=True, exist_ok=True)
    if purge_local_before_sync:
        purged_count = _purge_local_compliance_history_snapshots(compliance_history_dir)
        if purged_count:
            logging.debug(
                "Cleared %s local compliance_history snapshot(s) before ADLS sync",
                purged_count,
            )
    if not latest:
        if run_date is None:
            logging.debug(
                "No compliance_history snapshots found in ADLS prefix %s",
                remote_prefix,
            )
        else:
            comparator = "at or before" if include_run_date else "before"
            logging.debug(
                "No compliance_history snapshots found in ADLS prefix %s %s run_date=%s",
                remote_prefix,
                comparator,
                run_date,
            )
        return []

    selection = ", ".join(
        f"{slice_token}@{date_token}"
        for slice_token, (date_token, _) in sorted(latest.items())
    )
    if run_date is None:
        logging.debug(
            "Discovered %s latest compliance_history snapshot(s) from ADLS prefix %s: %s",
            len(latest),
            remote_prefix,
            selection,
        )
    else:
        bound = "<=" if include_run_date else "<"
        logging.debug(
            "Discovered %s latest compliance_history snapshot(s) from ADLS prefix %s (%s %s): %s",
            len(latest),
            remote_prefix,
            bound,
            run_date,
            selection,
        )

    downloaded: list[Path] = []
    ordered = sorted(latest.items())
    for slice_token, (date_token, remote) in tqdm(
        ordered,
        desc="ADLS sync compliance_history",
        unit="slice",
    ):
        local_path = compliance_history_dir / Path(remote).name
        logging.debug(
            "Syncing compliance_history %s (%s): %s -> %s",
            slice_token,
            date_token,
            remote,
            local_path,
        )
        download_file(file_system_client, remote, local_path)
        downloaded.append(local_path)
    logging.debug(
        "Synced %s compliance_history snapshot(s) to %s",
        len(downloaded),
        compliance_history_dir,
    )
    return downloaded
