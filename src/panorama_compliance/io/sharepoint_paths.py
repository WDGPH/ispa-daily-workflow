from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import quote, unquote, urlparse, urlunparse

from msgraph import GraphServiceClient
from msgraph.generated.models.drive import Drive

from panorama_compliance.io.sharepoint_graph import (
    GRAPH_ROOT,
    GraphRequestError,
    _graph_collect,
    _run_graph,
)

SHAREPOINT_DESTINATION_KEYS = (
    "inputs.panorama_overdue",
    "inputs.pear_overdue",
    "inputs.pear_suspension_vs_overdue",
    "inputs.pear_suspension",
    "outputs.list_difference",
    "outputs.action_queue",
    "outputs.pdf.elementary_root",
    "outputs.pdf.secondary_root",
)


@dataclass(frozen=True)
class SharePointLocation:
    folder_url: str
    host: str
    site_id: str
    drive_id: str
    drive_name: str
    drive_web_url: str | None
    folder_path: str


def _destination_url(settings, destination_key: str) -> str:
    if destination_key not in SHAREPOINT_DESTINATION_KEYS:
        raise KeyError(
            f"Unknown SharePoint destination key: {destination_key}. "
            f"Expected one of: {', '.join(SHAREPOINT_DESTINATION_KEYS)}"
        )
    value = _destination_value(settings, destination_key)
    if not value:
        raise ValueError(
            f"SharePoint destination URL is not configured for {destination_key}"
        )
    return str(value)


def _destination_value(settings, destination_key: str) -> str | None:
    if destination_key == "inputs.panorama_overdue":
        return settings.inputs.panorama_overdue
    if destination_key == "inputs.pear_overdue":
        return settings.inputs.pear_overdue
    if destination_key == "inputs.pear_suspension_vs_overdue":
        return settings.inputs.pear_suspension_vs_overdue
    if destination_key == "inputs.pear_suspension":
        return settings.inputs.pear_suspension
    if destination_key == "outputs.list_difference":
        return settings.outputs.list_difference
    if destination_key == "outputs.action_queue":
        return settings.outputs.action_queue
    if destination_key == "outputs.pdf.elementary_root":
        return settings.outputs.pdf.elementary_root
    if destination_key == "outputs.pdf.secondary_root":
        return settings.outputs.pdf.secondary_root
    raise KeyError(
        f"Unknown SharePoint destination key: {destination_key}. "
        f"Expected one of: {', '.join(SHAREPOINT_DESTINATION_KEYS)}"
    )


def _append_folder_url(folder_url: str, *segments: str) -> str:
    parsed = urlparse(folder_url)
    if not parsed.netloc:
        raise ValueError(f"Invalid SharePoint folder URL: {folder_url}")

    path_parts = [part for part in parsed.path.split("/") if part]
    for segment in segments:
        if not segment:
            continue
        for piece in str(segment).replace("\\", "/").split("/"):
            clean = piece.strip()
            if not clean:
                continue
            if clean in {".", ".."}:
                raise ValueError(
                    f"Invalid SharePoint folder segment {clean!r} for {folder_url}"
                )
            path_parts.append(quote(clean, safe=""))

    new_path = "/" + "/".join(path_parts)
    return urlunparse(
        (
            parsed.scheme,
            parsed.netloc,
            new_path,
            parsed.params,
            parsed.query,
            parsed.fragment,
        )
    )


def _resolve_location(
    client: GraphServiceClient,
    folder_url: str,
    *,
    cache: dict[str, SharePointLocation] | None = None,
) -> SharePointLocation:
    cached = cache.get(folder_url) if cache is not None else None
    if cached is not None:
        return cached

    parsed = urlparse(folder_url)
    if not parsed.netloc:
        raise ValueError(f"Invalid SharePoint folder URL: {folder_url}")

    segments = [unquote(part) for part in parsed.path.split("/") if part]
    if len(segments) < 3:
        raise ValueError(
            "Expected a SharePoint URL like "
            "https://<host>/sites/<site>/<library>/<optional/folder/path>"
        )
    if segments[0] not in {"sites", "teams"}:
        raise ValueError(
            "Expected SharePoint URL path to start with /sites/... or /teams/..., "
            f"got: {parsed.path}"
        )

    host = parsed.netloc
    last_not_found: GraphRequestError | None = None
    for split_index in range(2, len(segments)):
        site_segments = segments[:split_index]
        drive_segments = segments[split_index:]
        if not drive_segments:
            continue

        site_endpoint = (
            f"{GRAPH_ROOT}/sites/{host}:{_encode_path(site_segments)}?$select=id,webUrl"
        )
        try:
            site_payload = _run_graph(
                client.sites.by_site_id("root").with_url(site_endpoint).get(),
                method="GET",
                url=site_endpoint,
            )
        except GraphRequestError as exc:
            if exc.status_code == 404:
                last_not_found = exc
                continue
            raise

        if site_payload is None:
            raise ValueError(
                f"Unexpected Graph payload for site lookup: {site_endpoint}"
            )
        site_id = _extract_site_id(site_payload)
        if not site_id:
            raise ValueError(f"Graph site lookup returned no id for {site_endpoint}")

        library_name = drive_segments[0]
        folder_segments = drive_segments[1:]
        drives_endpoint = (
            f"{GRAPH_ROOT}/sites/{site_id}/drives?$select=id,name,webUrl,driveType"
        )
        drives_builder = client.sites.by_site_id(site_id).drives
        for drive in _graph_collect(drives_builder, url=drives_endpoint):
            if not isinstance(drive, Drive):
                continue
            drive_id = drive.id
            drive_name = str(drive.name or "")
            if not isinstance(drive_id, str):
                continue
            drive_web_url = str(drive.web_url or "")
            if not _drive_matches(library_name, drive_name, drive_web_url):
                continue

            location = SharePointLocation(
                folder_url=folder_url,
                host=host,
                site_id=site_id,
                drive_id=drive_id,
                drive_name=drive_name,
                drive_web_url=drive_web_url or None,
                folder_path=_normalize_remote_path("/".join(folder_segments)),
            )
            if cache is not None:
                cache[folder_url] = location
            return location

    if last_not_found is not None:
        raise last_not_found
    raise RuntimeError(
        "Unable to resolve site and document library from SharePoint folder URL: "
        f"{folder_url}"
    )


def _extract_site_id(payload: object) -> str | None:
    direct = getattr(payload, "id", None)
    if isinstance(direct, str) and direct:
        return direct

    additional_data = getattr(payload, "additional_data", None)
    if isinstance(additional_data, dict):
        value = additional_data.get("id")
        if isinstance(value, str) and value:
            return value

    values = getattr(payload, "value", None)
    if isinstance(values, list):
        for item in values:
            nested_id = getattr(item, "id", None)
            if isinstance(nested_id, str) and nested_id:
                return nested_id
            nested_data = getattr(item, "additional_data", None)
            if isinstance(nested_data, dict):
                nested_value = nested_data.get("id")
                if isinstance(nested_value, str) and nested_value:
                    return nested_value

    return None


def _drive_matches(library_name: str, drive_name: str, drive_web_url: str) -> bool:
    normalized_library = library_name.casefold()
    aliases = {normalized_library}
    if normalized_library == "shared documents":
        aliases.add("documents")

    if drive_name.casefold() in aliases:
        return True
    if drive_web_url:
        drive_path = unquote(urlparse(drive_web_url).path).casefold()
        if drive_path.endswith(f"/{normalized_library}"):
            return True
    return False


def _combine_remote_path(parent: str, leaf: str) -> str:
    normalized_parent = _normalize_remote_path(parent)
    _validate_leaf_name(leaf)
    return f"{normalized_parent}/{leaf}" if normalized_parent else leaf


def _normalize_remote_path(path: str) -> str:
    segments: list[str] = []
    for raw in path.split("/"):
        value = raw.strip()
        if not value:
            continue
        if value in {".", ".."}:
            raise ValueError(f"Invalid path segment in SharePoint path: {value}")
        if "\\" in value:
            raise ValueError(f"Invalid path segment in SharePoint path: {value}")
        segments.append(value)
    return "/".join(segments)


def _validate_leaf_name(name: str) -> None:
    if not name or name in {".", ".."}:
        raise ValueError(f"Invalid SharePoint filename: {name!r}")
    if "/" in name or "\\" in name:
        raise ValueError(
            f"SharePoint filename must not contain path separators: {name!r}"
        )


def _encode_path(segments: list[str]) -> str:
    return "/" + "/".join(quote(segment, safe="") for segment in segments)
