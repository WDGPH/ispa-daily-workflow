from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import unquote, urlparse

from ispa_daily_workflow.domain.delivery.routing import DeliveryScope

PROJECT_ROOT = Path(__file__).resolve().parents[4]


def sanitize_path_component(value: str) -> str:
    cleaned = re.sub(r"[^\w.=+-]+", "_", value.strip())
    cleaned = cleaned.strip("._-")
    return cleaned or "value"


def resolve_local_inspection_root(
    *,
    output_root: Path,
    run_date: str,
    source: str,
    upload_enabled: bool,
    download_enabled: bool,
    output_id: str,
    scope: DeliveryScope,
) -> Path:
    scope_value = "ALL" if scope.is_all else scope.normalized_value
    scope_token = sanitize_path_component(f"{scope.dimension}={scope_value}")
    output_token = sanitize_path_component(output_id)
    source_token = sanitize_path_component(f"source={source}")
    io_token = f"io=u{int(upload_enabled)}_d{int(download_enabled)}"
    return (
        output_root
        / "inspect"
        / run_date
        / source_token
        / io_token
        / output_token
        / scope_token
    )


def format_output_path(path: Path, *, verbose: bool) -> str:
    if verbose:
        return str(path)
    if path.is_absolute():
        try:
            output = str(path.relative_to(PROJECT_ROOT))
            return truncate_text(output)
        except ValueError:
            return truncate_text(str(path))
    return truncate_text(str(path))


def truncate_text(text: str, *, max_length: int = 120) -> str:
    if len(text) <= max_length:
        return text
    head = max(32, (max_length - 3) // 2)
    tail = max_length - head - 3
    return f"{text[:head]}...{text[-tail:]}"


def format_cleanup_entry(entry: str, *, verbose: bool) -> str:
    if verbose:
        return entry
    folder_url, sep, filename = entry.partition("::")
    if not sep:
        return entry
    parsed = urlparse(folder_url)
    folder_name = unquote(parsed.path.rstrip("/").split("/")[-1]) or folder_url
    return f"{folder_name}::{filename}"


def pdf_school_status_counts(generated_paths: list[Path]) -> tuple[int, int]:
    final_count = 0
    for path in generated_paths:
        name = path.name.upper()
        if name.endswith(
            ("_ISPA_FINAL_SUMMARY.PDF", "_ISPA_SUSPENSION_PERIOD_COMPLETE.PDF")
        ):
            final_count += 1
    return final_count, len(generated_paths) - final_count
