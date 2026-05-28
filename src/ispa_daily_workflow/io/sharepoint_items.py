from __future__ import annotations

import logging
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

from msgraph import GraphServiceClient
from msgraph.generated.models.drive_item import DriveItem
from msgraph.generated.models.folder import Folder

from ispa_daily_workflow.io.sharepoint_graph import (
    GRAPH_ROOT,
    GraphRequestError,
    _graph_collect,
    _run_graph,
)
from ispa_daily_workflow.io.sharepoint_paths import (
    SharePointLocation,
    _combine_remote_path,
    _validate_leaf_name,
)
from ispa_daily_workflow.progress import tqdm

ITEM_SELECT_FIELDS = (
    "id,name,webUrl,size,createdDateTime,lastModifiedDateTime,file,folder,eTag,cTag"
)


@dataclass(frozen=True)
class SharePointItem:
    id: str
    name: str
    web_url: str
    size: int | None
    created: str | None
    last_modified: str | None
    is_file: bool
    is_folder: bool
    sha1_hash: str | None
    e_tag: str | None
    c_tag: str | None


@dataclass(frozen=True)
class SharePointDownload:
    item: SharePointItem
    local_path: Path


@dataclass(frozen=True)
class SharePointTransferResult:
    local_path: Path
    remote_name: str
    remote_web_url: str
    size_bytes: int


def _list_folder_item_payloads(
    client: GraphServiceClient,
    location: SharePointLocation,
) -> list[DriveItem]:
    if location.folder_path:
        endpoint = (
            f"{GRAPH_ROOT}/drives/{location.drive_id}/root:"
            f"/{quote(location.folder_path, safe='/')}:"
            f"/children?$select={ITEM_SELECT_FIELDS}"
        )
    else:
        endpoint = (
            f"{GRAPH_ROOT}/drives/{location.drive_id}/root/children"
            f"?$select={ITEM_SELECT_FIELDS}"
        )

    builder = (
        client.drives.by_drive_id(location.drive_id)
        .items.by_drive_item_id("root")
        .children
    )
    payloads = _graph_collect(builder, url=endpoint)
    return [item for item in payloads if isinstance(item, DriveItem)]


def _list_drive_item_children(
    client: GraphServiceClient,
    *,
    drive_id: str,
    item_id: str,
) -> list[DriveItem]:
    endpoint = (
        f"{GRAPH_ROOT}/drives/{drive_id}/items/{item_id}/children"
        f"?$select={ITEM_SELECT_FIELDS}"
    )
    builder = (
        client.drives.by_drive_id(drive_id).items.by_drive_item_id(item_id).children
    )
    payloads = _graph_collect(builder, url=endpoint)
    return [item for item in payloads if isinstance(item, DriveItem)]


def _list_folder_item_payloads_recursive(
    client: GraphServiceClient,
    location: SharePointLocation,
    *,
    root_item_id: str,
    max_depth: int | None = None,
) -> list[DriveItem]:
    queue: deque[tuple[str, int]] = deque([(root_item_id, 0)])
    visited: set[str] = set()
    payloads: list[DriveItem] = []

    with tqdm(desc="SharePoint scan folders", unit="folder") as progress:
        while queue:
            folder_item_id, folder_depth = queue.popleft()
            if not folder_item_id or folder_item_id in visited:
                continue
            visited.add(folder_item_id)
            progress.update(1)

            children = _list_drive_item_children(
                client,
                drive_id=location.drive_id,
                item_id=folder_item_id,
            )
            for child in children:
                payloads.append(child)
                if child.folder is None or not child.id:
                    continue
                child_depth = folder_depth + 1
                if max_depth is not None and child_depth > max_depth:
                    continue
                queue.append((str(child.id), child_depth))

    return payloads


def _payload_to_item(payload: DriveItem) -> SharePointItem:
    file_payload = payload.file
    hashes = file_payload.hashes if file_payload is not None else None

    return SharePointItem(
        id=str(payload.id or ""),
        name=str(payload.name or ""),
        web_url=str(payload.web_url or ""),
        size=payload.size if isinstance(payload.size, int) else None,
        created=_timestamp_to_iso(payload.created_date_time),
        last_modified=_timestamp_to_iso(payload.last_modified_date_time),
        is_file=file_payload is not None,
        is_folder=payload.folder is not None,
        sha1_hash=(
            str(hashes.sha1_hash)
            if hashes is not None and hashes.sha1_hash is not None
            else None
        ),
        e_tag=str(payload.e_tag) if payload.e_tag is not None else None,
        c_tag=str(payload.c_tag) if payload.c_tag is not None else None,
    )


def _download_item(
    client: GraphServiceClient,
    location: SharePointLocation,
    item: SharePointItem,
    target_path: Path,
) -> None:
    endpoint = f"{GRAPH_ROOT}/drives/{location.drive_id}/items/{item.id}/content"
    raw = _run_graph(
        client.drives.by_drive_id(location.drive_id)
        .items.by_drive_item_id(item.id)
        .content.get(),
        method="GET",
        url=endpoint,
    )
    if not isinstance(raw, bytes):
        raise RuntimeError(f"Download did not return bytes for {item.name}")

    target_path.parent.mkdir(parents=True, exist_ok=True)
    target_path.write_bytes(raw)


def _upload_file(
    client: GraphServiceClient,
    location: SharePointLocation,
    *,
    local_path: Path,
    remote_name: str,
    overwrite: bool,
    parent_item_id_cache: dict[tuple[str, str], str] | None = None,
) -> SharePointTransferResult:
    _validate_leaf_name(remote_name)
    payload = local_path.read_bytes()
    local_size = len(payload)

    parent_item_id = _resolve_parent_item_id(
        client,
        location,
        cache=parent_item_id_cache,
    )
    conflict_behavior = "replace" if overwrite else "fail"
    endpoint = (
        f"{GRAPH_ROOT}/drives/{location.drive_id}/items/{parent_item_id}:"
        f"/{quote(remote_name, safe='')}"
        ":/content"
        f"?@microsoft.graph.conflictBehavior={conflict_behavior}"
    )

    try:
        item_payload = _run_graph(
            client.drives.by_drive_id(location.drive_id)
            .items.by_drive_item_id(parent_item_id)
            .content.with_url(endpoint)
            .put(payload),
            method="PUT",
            url=endpoint,
        )
    except GraphRequestError as exc:
        if not overwrite and exc.status_code == 409:
            raise FileExistsError(
                f"SharePoint file already exists and overwrite=False: {remote_name}"
            ) from exc
        raise

    if not isinstance(item_payload, DriveItem):
        raise RuntimeError(f"Unexpected upload response payload for {local_path}")

    item = _payload_to_item(item_payload)
    if not item.is_file:
        raise OSError(f"Upload response is not a file item for {local_path}")
    if item.name != remote_name:
        raise OSError(
            f"Upload name mismatch for {local_path}: expected {remote_name}, got {item.name}"
        )

    return SharePointTransferResult(
        local_path=local_path,
        remote_name=item.name,
        remote_web_url=item.web_url,
        size_bytes=local_size,
    )


def _resolve_parent_item_id(
    client: GraphServiceClient,
    location: SharePointLocation,
    *,
    cache: dict[tuple[str, str], str] | None = None,
) -> str:
    cache_key = (location.drive_id, location.folder_path)
    cached = cache.get(cache_key) if cache is not None else None
    if cached:
        return cached

    if location.folder_path:
        endpoint = (
            f"{GRAPH_ROOT}/drives/{location.drive_id}/root:"
            f"/{quote(location.folder_path, safe='/')}"
            "?$select=id"
        )
    else:
        endpoint = f"{GRAPH_ROOT}/drives/{location.drive_id}/root?$select=id"

    payload = _run_graph(
        client.drives.by_drive_id(location.drive_id)
        .items.by_drive_item_id("root")
        .with_url(endpoint)
        .get(),
        method="GET",
        url=endpoint,
    )
    if not isinstance(payload, DriveItem):
        raise RuntimeError(
            f"Unexpected folder metadata response for {location.folder_url}"
        )

    parent_id = payload.id
    if not isinstance(parent_id, str) or not parent_id:
        raise RuntimeError(f"Folder id not returned for {location.folder_url}")

    if cache is not None:
        cache[cache_key] = parent_id
    return parent_id


def _ensure_folder_exists(
    client: GraphServiceClient,
    location: SharePointLocation,
    *,
    parent_item_id_cache: dict[tuple[str, str], str] | None = None,
) -> None:
    if not location.folder_path:
        return

    root_item_builder = client.drives.by_drive_id(
        location.drive_id
    ).items.by_drive_item_id("root")
    root_children_builder = root_item_builder.children

    parent = ""
    created_or_existing_id: str | None = None
    for segment in location.folder_path.split("/"):
        if not segment:
            continue

        candidate = _combine_remote_path(parent, segment)
        exists_endpoint = (
            f"{GRAPH_ROOT}/drives/{location.drive_id}/root:"
            f"/{quote(candidate, safe='/')}?$select=id"
        )
        try:
            payload = _run_graph(
                root_item_builder.with_url(exists_endpoint).get(),
                method="GET",
                url=exists_endpoint,
            )
            if not isinstance(payload, DriveItem):
                raise RuntimeError(
                    f"Unexpected folder metadata response for {location.folder_url}"
                )
            created_or_existing_id = str(payload.id or "")
            parent = candidate
            continue
        except GraphRequestError as exc:
            if exc.status_code != 404:
                raise

        if parent:
            create_endpoint = (
                f"{GRAPH_ROOT}/drives/{location.drive_id}/root:"
                f"/{quote(parent, safe='/')}:/children"
            )
        else:
            create_endpoint = f"{GRAPH_ROOT}/drives/{location.drive_id}/root/children"

        created = _run_graph(
            root_children_builder.with_url(create_endpoint).post(
                DriveItem(
                    name=segment,
                    folder=Folder(),
                    additional_data={"@microsoft.graph.conflictBehavior": "fail"},
                )
            ),
            method="POST",
            url=create_endpoint,
        )
        if not isinstance(created, DriveItem):
            raise RuntimeError(
                f"Unexpected folder create response for drive={location.drive_id}"
            )

        created_or_existing_id = str(created.id or "")
        parent = candidate

    if parent_item_id_cache is not None and created_or_existing_id:
        parent_item_id_cache[(location.drive_id, location.folder_path)] = (
            created_or_existing_id
        )


def _normalize_suffixes(values: set[str] | None) -> set[str]:
    if not values:
        return set()
    normalized: set[str] = set()
    for value in values:
        suffix = value.lower()
        if not suffix.startswith("."):
            suffix = f".{suffix}"
        normalized.add(suffix)
    return normalized


def _parse_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    candidate = value
    if candidate.endswith("Z"):
        candidate = f"{candidate[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError:
        logging.warning("Unable to parse SharePoint timestamp: %s", value)
        return None
    return parsed.astimezone(timezone.utc)


def _timestamp_to_iso(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        parsed = value.astimezone(timezone.utc)
    else:
        parsed = _parse_timestamp(str(value))
        if parsed is None:
            return str(value)
    return parsed.isoformat().replace("+00:00", "Z")
