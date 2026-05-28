from __future__ import annotations

import asyncio
import atexit
import logging
from collections.abc import Awaitable
from typing import Any, TypeVar

from azure.identity.aio import ClientSecretCredential
from kiota_abstractions.api_error import APIError
from msgraph import GraphServiceClient

GRAPH_ROOT = "https://graph.microsoft.com/v1.0"
GRAPH_SCOPE = "https://graph.microsoft.com/.default"


class GraphRequestError(RuntimeError):
    def __init__(self, status_code: int, method: str, url: str, body: str):
        super().__init__(
            f"Graph API request failed ({status_code}) for {method} {url}: {body}"
        )
        self.status_code = status_code
        self.method = method
        self.url = url
        self.body = body


def _read_secret(settings: Any, key: str) -> str:
    filename = settings.secret_files.get(key)
    if not filename:
        raise KeyError(f"SharePoint secret_files is missing key: {key}")
    return (settings.secrets_path / filename).read_text(encoding="utf-8").strip()


_ResponseT = TypeVar("_ResponseT")
_GRAPH_LOOP: asyncio.AbstractEventLoop | None = None


def _get_graph_loop() -> asyncio.AbstractEventLoop:
    global _GRAPH_LOOP
    loop = _GRAPH_LOOP
    if loop is None or loop.is_closed():
        loop = asyncio.new_event_loop()
        _GRAPH_LOOP = loop
    return loop


@atexit.register
def _close_graph_loop() -> None:
    global _GRAPH_LOOP
    loop = _GRAPH_LOOP
    if loop is None:
        return
    if loop.is_running():
        return
    if not loop.is_closed():
        loop.close()
    _GRAPH_LOOP = None


def _get_graph_client(
    settings: Any,
) -> tuple[GraphServiceClient, ClientSecretCredential]:
    tenant_id = _read_secret(settings, "tenant_id")
    client_id = _read_secret(settings, "client_id")
    client_secret = _read_secret(settings, "client_secret")
    credential = ClientSecretCredential(
        tenant_id=tenant_id,
        client_id=client_id,
        client_secret=client_secret,
    )
    client = GraphServiceClient(credentials=credential, scopes=[GRAPH_SCOPE])
    return client, credential


def _close_graph_client(
    client: GraphServiceClient,
    credential: ClientSecretCredential,
) -> None:
    http_client = getattr(client.request_adapter, "_http_client", None)
    if http_client is not None and hasattr(http_client, "aclose"):
        try:
            _run(http_client.aclose())
        except Exception:
            logging.debug("SharePoint Graph HTTP client close failed", exc_info=True)
    try:
        _run(credential.close())
    except Exception:
        logging.debug("SharePoint credential close failed", exc_info=True)


def _run(coro: Awaitable[_ResponseT]) -> _ResponseT:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        pass
    else:
        raise RuntimeError(
            "SharePoint SDK helpers were called from an active event loop. "
            "Use async-safe wrappers for this call path."
        )
    loop = _get_graph_loop()
    return loop.run_until_complete(coro)


def _graph_error_body(exc: APIError) -> str:
    body_parts: list[str] = []
    odata_error = getattr(exc, "error", None)
    if odata_error is not None:
        code = getattr(odata_error, "code", None)
        message = getattr(odata_error, "message", None)
        if code:
            body_parts.append(f"code={code}")
        if message:
            body_parts.append(str(message))
    if not body_parts and getattr(exc, "message", None):
        body_parts.append(str(exc.message))
    text = str(exc).strip()
    if text:
        body_parts.append(text)
    return " | ".join(part for part in body_parts if part)


def _map_api_error(exc: APIError, method: str, url: str) -> GraphRequestError:
    status_code = exc.response_status_code
    status = int(status_code) if status_code is not None else 0
    body = _graph_error_body(exc)
    return GraphRequestError(status, method, url, body)


def _run_graph(coro: Awaitable[_ResponseT], *, method: str, url: str) -> _ResponseT:
    try:
        return _run(coro)
    except APIError as exc:
        raise _map_api_error(exc, method, url) from exc


def _graph_collect(builder: Any, *, url: str) -> list[Any]:
    items: list[Any] = []
    next_url: str | None = url
    while next_url:
        response = _run_graph(
            builder.with_url(next_url).get(),
            method="GET",
            url=next_url,
        )
        if response is None:
            break
        values = getattr(response, "value", None)
        if isinstance(values, list):
            items.extend(values)
        next_link = getattr(response, "odata_next_link", None)
        next_url = next_link if isinstance(next_link, str) and next_link else None
    return items
