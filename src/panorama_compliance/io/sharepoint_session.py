from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from azure.identity.aio import ClientSecretCredential
from msgraph import GraphServiceClient

from panorama_compliance.io.sharepoint_graph import (
    GRAPH_ROOT,
    _close_graph_client,
    _get_graph_client,
    _run_graph,
)
from panorama_compliance.io.sharepoint_items import (
    SharePointDownload,
    SharePointItem,
    SharePointTransferResult,
    _download_item,
    _ensure_folder_exists,
    _list_folder_item_payloads,
    _list_folder_item_payloads_recursive,
    _normalize_suffixes,
    _parse_timestamp,
    _payload_to_item,
    _resolve_parent_item_id,
    _upload_file,
)
from panorama_compliance.io.sharepoint_paths import (
    SharePointLocation,
    _destination_url,
    _resolve_location,
    _validate_leaf_name,
)
from panorama_compliance.io.sharepoint_settings import SharePointSettings
from panorama_compliance.progress import tqdm


class SharePointSession:
    def __init__(self, settings: SharePointSettings):
        self.settings = settings
        self._client: GraphServiceClient | None = None
        self._credential: ClientSecretCredential | None = None
        self._location_cache: dict[str, SharePointLocation] = {}
        self._parent_item_id_cache: dict[tuple[str, str], str] = {}

    def __enter__(self) -> SharePointSession:
        self._client, self._credential = _get_graph_client(self.settings)
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> bool:
        self.close()
        return False

    def close(self) -> None:
        if self._client is None or self._credential is None:
            return
        _close_graph_client(self._client, self._credential)
        self._client = None
        self._credential = None

    @property
    def client(self) -> GraphServiceClient:
        if self._client is None:
            raise RuntimeError(
                "SharePointSession is not active. Use it as a context manager."
            )
        return self._client

    def resolve_location(self, folder_url: str) -> SharePointLocation:
        return _resolve_location(
            self.client,
            folder_url,
            cache=self._location_cache,
        )

    def download_folder_files(
        self,
        *,
        folder_url: str,
        output_dir: Path,
        allowed_suffixes: set[str] | None = None,
        overwrite: bool = False,
        recursive: bool = False,
        max_depth: int | None = None,
    ) -> list[Path]:
        items = self.list_folder_items(
            folder_url=folder_url,
            recursive=recursive,
            max_depth=max_depth,
        )
        suffixes = _normalize_suffixes(allowed_suffixes)
        selected = [
            item
            for item in items
            if item.is_file
            and (not suffixes or Path(item.name).suffix.lower() in suffixes)
        ]
        downloads = self.download_folder_items(
            folder_url=folder_url,
            output_dir=output_dir,
            items=selected,
            overwrite=overwrite,
        )
        return [entry.local_path for entry in downloads]

    def list_folder_items(
        self,
        *,
        folder_url: str,
        recursive: bool = False,
        max_depth: int | None = None,
    ) -> list[SharePointItem]:
        if max_depth is not None and max_depth < 0:
            raise ValueError(f"max_depth must be >= 0, got {max_depth}")
        location = self.resolve_location(folder_url)
        if recursive:
            root_item_id = _resolve_parent_item_id(
                self.client,
                location,
                cache=self._parent_item_id_cache,
            )
            payloads = _list_folder_item_payloads_recursive(
                self.client,
                location,
                root_item_id=root_item_id,
                max_depth=max_depth,
            )
        else:
            payloads = _list_folder_item_payloads(self.client, location)
        return sorted(
            (_payload_to_item(payload) for payload in payloads),
            key=lambda item: item.name.casefold(),
        )

    def download_folder_items(
        self,
        *,
        folder_url: str,
        output_dir: Path,
        items: list[SharePointItem],
        overwrite: bool = False,
    ) -> list[SharePointDownload]:
        location = self.resolve_location(folder_url)
        output_dir.mkdir(parents=True, exist_ok=True)

        seen_targets: set[str] = set()
        downloaded: list[SharePointDownload] = []
        ordered = sorted(items, key=lambda value: value.name.casefold())
        for item in tqdm(ordered, desc="SharePoint download", unit="file"):
            if not item.is_file:
                raise ValueError(
                    "SharePoint item is not a file and cannot be downloaded: "
                    f"{item.name!r}"
                )
            target = output_dir / item.name
            if target.name in seen_targets:
                raise ValueError(
                    f"Duplicate SharePoint filenames in download selection: {item.name}"
                )
            if target.exists() and not overwrite:
                raise FileExistsError(
                    f"Refusing to overwrite existing file without overwrite=True: {target}"
                )
            _download_item(self.client, location, item, target)
            seen_targets.add(target.name)
            downloaded.append(SharePointDownload(item=item, local_path=target))
        return downloaded

    def upload_files_to_folder(
        self,
        *,
        folder_url: str,
        paths: list[Path],
        overwrite: bool = True,
    ) -> list[SharePointTransferResult]:
        location = self.resolve_location(folder_url)
        if location.folder_path:
            _ensure_folder_exists(
                self.client,
                location,
                parent_item_id_cache=self._parent_item_id_cache,
            )

        uploaded: list[SharePointTransferResult] = []
        ordered = sorted(set(paths))
        for path in tqdm(ordered, desc="SharePoint upload", unit="file"):
            if not path.exists() or not path.is_file():
                raise FileNotFoundError(f"Upload path is not a file: {path}")
            _validate_leaf_name(path.name)
            uploaded.append(
                _upload_file(
                    self.client,
                    location,
                    local_path=path,
                    remote_name=path.name,
                    overwrite=overwrite,
                    parent_item_id_cache=self._parent_item_id_cache,
                )
            )
        return uploaded

    def delete_folder_files(
        self,
        *,
        folder_url: str,
        name_regex: str | None = None,
        suffixes: set[str] | None = None,
        older_than: datetime | None = None,
        dry_run: bool = False,
    ) -> list[str]:
        location = self.resolve_location(folder_url)
        payloads = _list_folder_item_payloads(self.client, location)
        pattern = re.compile(name_regex) if name_regex else None
        normalized_suffixes = _normalize_suffixes(suffixes)
        cutoff = older_than.astimezone(timezone.utc) if older_than else None

        deleted: list[str] = []
        for payload in sorted(
            payloads, key=lambda value: str(value.name or "").casefold()
        ):
            item = _payload_to_item(payload)
            if not item.is_file:
                continue
            if pattern and not pattern.search(item.name):
                continue
            if (
                normalized_suffixes
                and Path(item.name).suffix.lower() not in normalized_suffixes
            ):
                continue
            if cutoff is not None:
                modified = _parse_timestamp(item.last_modified)
                if modified is None or modified >= cutoff:
                    continue

            if not dry_run:
                endpoint = f"{GRAPH_ROOT}/drives/{location.drive_id}/items/{item.id}"
                _run_graph(
                    self.client.drives.by_drive_id(location.drive_id)
                    .items.by_drive_item_id(item.id)
                    .delete(),
                    method="DELETE",
                    url=endpoint,
                )
            deleted.append(item.name)

        return deleted


def download_destination_files(
    settings: SharePointSettings,
    *,
    destination_key: str,
    output_dir: Path,
    allowed_suffixes: set[str] | None = None,
    overwrite: bool = False,
    recursive: bool = False,
    max_depth: int | None = None,
) -> list[Path]:
    with SharePointSession(settings) as session:
        return session.download_folder_files(
            folder_url=_destination_url(settings, destination_key),
            output_dir=output_dir,
            allowed_suffixes=allowed_suffixes,
            overwrite=overwrite,
            recursive=recursive,
            max_depth=max_depth,
        )


def list_destination_items(
    settings: SharePointSettings,
    *,
    destination_key: str,
    recursive: bool = False,
    max_depth: int | None = None,
) -> list[SharePointItem]:
    with SharePointSession(settings) as session:
        return session.list_folder_items(
            folder_url=_destination_url(settings, destination_key),
            recursive=recursive,
            max_depth=max_depth,
        )


def download_destination_items(
    settings: SharePointSettings,
    *,
    destination_key: str,
    output_dir: Path,
    items: list[SharePointItem],
    overwrite: bool = False,
) -> list[SharePointDownload]:
    with SharePointSession(settings) as session:
        return session.download_folder_items(
            folder_url=_destination_url(settings, destination_key),
            output_dir=output_dir,
            items=items,
            overwrite=overwrite,
        )


def upload_files_to_destination(
    settings: SharePointSettings,
    *,
    destination_key: str,
    paths: list[Path],
    overwrite: bool = True,
) -> list[SharePointTransferResult]:
    with SharePointSession(settings) as session:
        return session.upload_files_to_folder(
            folder_url=_destination_url(settings, destination_key),
            paths=paths,
            overwrite=overwrite,
        )
