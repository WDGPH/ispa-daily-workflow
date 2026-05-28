from __future__ import annotations

import logging
import shutil
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from ispa_daily_workflow.config import (
    get_io_config,
    require_config_value,
)
from ispa_daily_workflow.io.adls import (
    COMPLIANCE_HISTORY_FILENAME_PATTERN,
    LANDING_CANONICAL_FILENAME_PATTERN,
    AdlsSettings,
    load_adls_settings,
)
from ispa_daily_workflow.io.adls import (
    discover_compliance_history_slices_for_date as adls_discover_compliance_history_slices_for_date,
)
from ispa_daily_workflow.io.adls import (
    download_files_for_date as adls_download_files_for_date,
)
from ispa_daily_workflow.io.adls import (
    download_latest_compliance_histories as adls_download_latest_compliance_histories,
)
from ispa_daily_workflow.io.adls import (
    upload_paths as adls_upload_paths,
)
from ispa_daily_workflow.io.sharepoint_items import SharePointItem
from ispa_daily_workflow.io.sharepoint_session import (
    download_destination_items,
    list_destination_items,
    upload_files_to_destination,
)
from ispa_daily_workflow.io.sharepoint_settings import (
    SharePointSettings,
    load_sharepoint_settings,
)


class InputProvider(Protocol):
    @property
    def name(self) -> str: ...

    def fetch_files(
        self,
        *,
        destination_keys: Sequence[str],
        output_dir: Path,
        overwrite: bool,
        suffix: str = ".xlsx",
    ) -> list[Path]: ...


class StateStore(Protocol):
    @property
    def name(self) -> str: ...

    def download_files_for_date(
        self,
        *,
        run_date: str,
        output_dir: Path,
        prefix: str | None = None,
        filename_pattern=LANDING_CANONICAL_FILENAME_PATTERN,
    ) -> list[Path]: ...

    def download_latest_compliance_histories(
        self,
        *,
        compliance_history_dir: Path,
        run_date: str | None = None,
        include_run_date: bool = True,
        purge_local_before_sync: bool = False,
        prefix: str | None = None,
    ) -> list[Path]: ...

    def discover_compliance_history_slices_for_date(
        self,
        *,
        run_date: str,
        prefix: str | None = None,
    ) -> list[str]: ...

    def upload_paths(
        self,
        *,
        paths: list[Path],
        prefix: str | None = None,
    ) -> list[str]: ...


class OutputPublisher(Protocol):
    @property
    def name(self) -> str: ...

    def publish_files(
        self,
        *,
        destination_key: str,
        paths: list[Path],
        overwrite: bool,
    ) -> list[str]: ...


def _adapter_cfg(config: dict, key: str) -> dict[str, object]:
    io_cfg = get_io_config(config)
    raw = io_cfg.get(key, {})
    return raw if isinstance(raw, dict) else {}


def _adapter_kind(config: dict, key: str, *, default: str) -> str:
    raw = _adapter_cfg(config, key).get("kind", default)
    return str(raw).strip().lower()


def _require_local_root(config: dict, key: str) -> Path:
    cfg = _adapter_cfg(config, key)
    root = require_config_value(cfg, "root", label=f"io.{key}.root")
    return Path(str(root)).expanduser()


def _prefix_dir(root: Path, prefix: str | None) -> Path:
    if prefix is None or not str(prefix).strip():
        return root
    return root / str(prefix).strip("/")


def _copy_or_reference(source: Path, target: Path, *, overwrite: bool = True) -> Path:
    target.parent.mkdir(parents=True, exist_ok=True)
    if source.resolve() == target.resolve():
        return target
    if target.exists() and not overwrite:
        return target
    shutil.copy2(source, target)
    return target


def _destination_subdir(destination_key: str) -> Path:
    safe_parts = [
        part.strip().replace("/", "_")
        for part in destination_key.split(".")
        if part.strip()
    ]
    return Path(*safe_parts) if safe_parts else Path("default")


@dataclass(frozen=True)
class LocalInputProvider:
    root: Path
    name: str = "local"

    def fetch_files(
        self,
        *,
        destination_keys: Sequence[str],
        output_dir: Path,
        overwrite: bool,
        suffix: str = ".xlsx",
    ) -> list[Path]:
        candidate_roots: list[Path] = []
        for key in destination_keys:
            keyed = self.root / _destination_subdir(key)
            candidate_roots.append(keyed if keyed.exists() else self.root)
        if not candidate_roots:
            candidate_roots.append(self.root)

        by_name: dict[str, Path] = {}
        for root in candidate_roots:
            if not root.exists():
                continue
            for path in sorted(root.glob(f"*{suffix}")):
                if path.is_file():
                    by_name.setdefault(path.name.casefold(), path)

        return [
            _copy_or_reference(path, output_dir / path.name, overwrite=overwrite)
            for path in sorted(
                by_name.values(), key=lambda value: value.name.casefold()
            )
        ]


@dataclass(frozen=True)
class SharePointInputProvider:
    settings: SharePointSettings
    name: str = "sharepoint"

    def fetch_files(
        self,
        *,
        destination_keys: Sequence[str],
        output_dir: Path,
        overwrite: bool,
        suffix: str = ".xlsx",
    ) -> list[Path]:
        output_dir.mkdir(parents=True, exist_ok=True)
        selected_by_id: dict[str, tuple[str, SharePointItem]] = {}
        selected_name_to_id: dict[str, str] = {}

        for destination_key in destination_keys:
            items = list_destination_items(
                self.settings,
                destination_key=destination_key,
                recursive=False,
            )
            for item in items:
                if not item.is_file:
                    continue
                if Path(item.name).suffix.lower() != suffix.lower():
                    continue
                if item.id in selected_by_id:
                    continue
                name_token = item.name.casefold()
                existing_id = selected_name_to_id.get(name_token)
                if existing_id is not None and existing_id != item.id:
                    logging.warning(
                        "Input filename collision for %s across source keys; "
                        "keeping first encountered file id=%s and skipping id=%s",
                        item.name,
                        existing_id,
                        item.id,
                    )
                    continue
                selected_by_id[item.id] = (destination_key, item)
                selected_name_to_id[name_token] = item.id

        grouped: dict[str, list[SharePointItem]] = {}
        for destination_key, item in selected_by_id.values():
            grouped.setdefault(destination_key, []).append(item)

        downloaded_paths: list[Path] = []
        for destination_key in destination_keys:
            items = sorted(
                grouped.get(destination_key, []),
                key=lambda value: value.name.casefold(),
            )
            if not items:
                continue
            downloads = download_destination_items(
                self.settings,
                destination_key=destination_key,
                output_dir=output_dir,
                items=items,
                overwrite=overwrite,
            )
            downloaded_paths.extend(entry.local_path for entry in downloads)

        return sorted(set(downloaded_paths))


@dataclass(frozen=True)
class LocalStateStore:
    root: Path
    name: str = "local"

    def download_files_for_date(
        self,
        *,
        run_date: str,
        output_dir: Path,
        prefix: str | None = None,
        filename_pattern=LANDING_CANONICAL_FILENAME_PATTERN,
    ) -> list[Path]:
        source_dir = _prefix_dir(self.root, prefix)
        if not source_dir.exists():
            return []
        candidates = []
        for path in sorted(source_dir.rglob(f"{run_date}_*")):
            if not path.is_file():
                continue
            if filename_pattern is not None and not filename_pattern.match(path.name):
                continue
            candidates.append(path)
        return [_copy_or_reference(path, output_dir / path.name) for path in candidates]

    def download_latest_compliance_histories(
        self,
        *,
        compliance_history_dir: Path,
        run_date: str | None = None,
        include_run_date: bool = True,
        purge_local_before_sync: bool = False,
        prefix: str | None = None,
    ) -> list[Path]:
        source_dir = _prefix_dir(self.root, prefix)
        if not source_dir.exists():
            return []

        latest: dict[str, tuple[str, Path]] = {}
        for path in sorted(source_dir.rglob("*_panorama_*_compliance_history.parquet")):
            if not path.is_file():
                continue
            match = COMPLIANCE_HISTORY_FILENAME_PATTERN.match(path.name)
            if not match:
                continue
            date_token = match.group("date")
            if run_date is not None:
                if include_run_date and date_token > run_date:
                    continue
                if not include_run_date and date_token >= run_date:
                    continue
            slice_token = match.group("slice")
            existing = latest.get(slice_token)
            if existing is None or date_token > existing[0]:
                latest[slice_token] = (date_token, path)

        same_directory = False
        try:
            same_directory = source_dir.resolve() == compliance_history_dir.resolve()
        except FileNotFoundError:
            same_directory = False
        if (
            purge_local_before_sync
            and not same_directory
            and compliance_history_dir.exists()
        ):
            for path in compliance_history_dir.glob(
                "*_panorama_*_compliance_history.parquet"
            ):
                if path.is_file():
                    path.unlink()

        return [
            _copy_or_reference(path, compliance_history_dir / path.name)
            for _slice_token, (_date_token, path) in sorted(latest.items())
        ]

    def discover_compliance_history_slices_for_date(
        self,
        *,
        run_date: str,
        prefix: str | None = None,
    ) -> list[str]:
        source_dir = _prefix_dir(self.root, prefix)
        if not source_dir.exists():
            return []
        slices: set[str] = set()
        for path in source_dir.rglob(
            f"{run_date}_panorama_*_compliance_history.parquet"
        ):
            if not path.is_file():
                continue
            match = COMPLIANCE_HISTORY_FILENAME_PATTERN.match(path.name)
            if match:
                slices.add(match.group("slice"))
        return sorted(slices)

    def upload_paths(
        self,
        *,
        paths: list[Path],
        prefix: str | None = None,
    ) -> list[str]:
        target_dir = _prefix_dir(self.root, prefix)
        copied = [
            _copy_or_reference(path, target_dir / path.name)
            for path in sorted(set(paths))
        ]
        return [str(path) for path in copied]


@dataclass(frozen=True)
class AdlsStateStore:
    settings: AdlsSettings
    name: str = "adls"

    def download_files_for_date(
        self,
        *,
        run_date: str,
        output_dir: Path,
        prefix: str | None = None,
        filename_pattern=LANDING_CANONICAL_FILENAME_PATTERN,
    ) -> list[Path]:
        return adls_download_files_for_date(
            self.settings,
            run_date=run_date,
            output_dir=output_dir,
            prefix=prefix,
            filename_pattern=filename_pattern,
        )

    def download_latest_compliance_histories(
        self,
        *,
        compliance_history_dir: Path,
        run_date: str | None = None,
        include_run_date: bool = True,
        purge_local_before_sync: bool = False,
        prefix: str | None = None,
    ) -> list[Path]:
        return adls_download_latest_compliance_histories(
            self.settings,
            compliance_history_dir=compliance_history_dir,
            run_date=run_date,
            include_run_date=include_run_date,
            purge_local_before_sync=purge_local_before_sync,
            prefix=prefix,
        )

    def discover_compliance_history_slices_for_date(
        self,
        *,
        run_date: str,
        prefix: str | None = None,
    ) -> list[str]:
        return adls_discover_compliance_history_slices_for_date(
            self.settings,
            run_date=run_date,
            prefix=prefix,
        )

    def upload_paths(
        self,
        *,
        paths: list[Path],
        prefix: str | None = None,
    ) -> list[str]:
        return adls_upload_paths(self.settings, paths=paths, prefix=prefix)


@dataclass(frozen=True)
class LocalOutputPublisher:
    root: Path
    name: str = "local"

    def publish_files(
        self,
        *,
        destination_key: str,
        paths: list[Path],
        overwrite: bool,
    ) -> list[str]:
        destination_dir = self.root / _destination_subdir(destination_key)
        copied = [
            _copy_or_reference(path, destination_dir / path.name, overwrite=overwrite)
            for path in sorted(set(paths))
        ]
        return [str(path) for path in copied]


@dataclass(frozen=True)
class SharePointOutputPublisher:
    settings: SharePointSettings
    name: str = "sharepoint"

    def publish_files(
        self,
        *,
        destination_key: str,
        paths: list[Path],
        overwrite: bool,
    ) -> list[str]:
        uploaded = upload_files_to_destination(
            self.settings,
            destination_key=destination_key,
            paths=paths,
            overwrite=overwrite,
        )
        return [item.remote_web_url for item in uploaded]


def load_input_provider(config: dict) -> InputProvider:
    kind = _adapter_kind(config, "input_provider", default="sharepoint")
    if kind == "sharepoint":
        return SharePointInputProvider(load_sharepoint_settings(config))
    if kind == "local":
        return LocalInputProvider(_require_local_root(config, "input_provider"))
    raise ValueError(f"Unsupported io.input_provider.kind: {kind}")


def load_state_store(config: dict) -> StateStore:
    kind = _adapter_kind(config, "state_store", default="adls")
    if kind == "adls":
        return AdlsStateStore(load_adls_settings(config))
    if kind == "local":
        return LocalStateStore(_require_local_root(config, "state_store"))
    raise ValueError(f"Unsupported io.state_store.kind: {kind}")


def load_output_publisher(config: dict) -> OutputPublisher:
    kind = _adapter_kind(config, "output_publisher", default="sharepoint")
    if kind == "sharepoint":
        return SharePointOutputPublisher(load_sharepoint_settings(config))
    if kind == "local":
        return LocalOutputPublisher(_require_local_root(config, "output_publisher"))
    raise ValueError(f"Unsupported io.output_publisher.kind: {kind}")


def sharepoint_settings_for_publisher(
    publisher: OutputPublisher | None,
) -> SharePointSettings | None:
    if isinstance(publisher, SharePointOutputPublisher):
        return publisher.settings
    return None


__all__ = [
    "AdlsStateStore",
    "InputProvider",
    "LocalInputProvider",
    "LocalOutputPublisher",
    "LocalStateStore",
    "OutputPublisher",
    "SharePointInputProvider",
    "SharePointOutputPublisher",
    "StateStore",
    "load_input_provider",
    "load_output_publisher",
    "load_state_store",
    "sharepoint_settings_for_publisher",
]
