from __future__ import annotations

import hashlib
import json
from datetime import date
from pathlib import Path
from typing import Any, Sequence

import polars as pl

from panorama_compliance.models import FileManifest, ReportOutput


def _hash_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(chunk_size)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _prefixed_path(quality_dir: Path, timestamp: str) -> Path:
    quality_dir.mkdir(parents=True, exist_ok=True)
    return quality_dir / f"{timestamp}_manifest.json"


def _client_id_stats(df: pl.DataFrame) -> dict[str, int]:
    if "client_id" not in df.columns:
        return {
            "total_rows": df.height,
            "missing_client_id_count": df.height,
            "duplicate_client_id_count": 0,
        }

    normalized = df.with_columns(
        pl.col("client_id")
        .cast(pl.Utf8, strict=False)
        .str.strip_chars()
        .alias("client_id")
    )
    missing = normalized.filter(
        pl.col("client_id").is_null() | (pl.col("client_id") == "")
    ).height
    duplicate_keys = (
        normalized.filter(
            pl.col("client_id").is_not_null() & (pl.col("client_id") != "")
        )
        .group_by("client_id")
        .len()
        .filter(pl.col("len") > 1)
        .height
    )
    return {
        "total_rows": normalized.height,
        "missing_client_id_count": missing,
        "duplicate_client_id_count": duplicate_keys,
    }


def _exact_duplicates(manifests: Sequence[FileManifest]) -> list[dict[str, Any]]:
    hash_groups: dict[str, list[str]] = {}
    for entry in manifests:
        if not entry.path.exists():
            continue
        file_hash = _hash_file(entry.path)
        hash_groups.setdefault(file_hash, []).append(str(entry.path))

    return [
        {"hash": file_hash, "files": sorted(paths)}
        for file_hash, paths in hash_groups.items()
        if len(paths) > 1
    ]


def write_manifest(
    *,
    quality_dir: Path,
    timestamp: str,
    run_date: date,
    mode: str,
    manifests: Sequence[FileManifest] | None = None,
    datasets: dict[str, pl.DataFrame] | None = None,
    report_outputs: Sequence[ReportOutput] | None = None,
    file_outputs: Sequence[Path] | None = None,
    extra: dict[str, Any] | None = None,
) -> Path:
    payload = build_manifest_payload(
        timestamp=timestamp,
        run_date=run_date,
        mode=mode,
        manifests=manifests,
        datasets=datasets,
        report_outputs=report_outputs,
        file_outputs=file_outputs,
        extra=extra,
    )
    output_path = _prefixed_path(quality_dir, timestamp)
    output_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return output_path


def build_manifest_payload(
    *,
    timestamp: str,
    run_date: date,
    mode: str,
    manifests: Sequence[FileManifest] | None = None,
    datasets: dict[str, pl.DataFrame] | None = None,
    report_outputs: Sequence[ReportOutput] | None = None,
    file_outputs: Sequence[Path] | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    manifests = manifests or []
    datasets = datasets or {}
    report_outputs = report_outputs or []
    file_outputs = file_outputs or []

    input_payload = []
    for entry in manifests:
        payload = {
            "path": str(entry.path),
            "size_bytes": entry.size_bytes,
            "modified_time": entry.modified_time.isoformat(),
            "detected_format": entry.detected_format,
            "schema_errors": entry.schema_errors,
            "schema_warnings": entry.schema_warnings,
        }
        if entry.path.exists():
            payload["sha256"] = _hash_file(entry.path)
        if entry.path.name in datasets:
            payload["client_id_stats"] = _client_id_stats(datasets[entry.path.name])
            payload["row_count"] = datasets[entry.path.name].height
        input_payload.append(payload)

    dataset_payload = {
        name: {
            "row_count": frame.height,
            "client_id_stats": _client_id_stats(frame),
        }
        for name, frame in datasets.items()
    }

    report_payload = [
        {
            "report_type": entry.report_type,
            "school_label": entry.school_label,
            "pdf_path": str(entry.pdf_path),
            "counts": entry.counts,
            "id_stats": entry.id_stats,
        }
        for entry in report_outputs
    ]

    file_output_payload = []
    for path in file_outputs:
        record: dict[str, object] = {"path": str(path)}
        if path.exists():
            record["size_bytes"] = path.stat().st_size
            record["sha256"] = _hash_file(path)
        file_output_payload.append(record)

    payload = {
        "generated_at": timestamp,
        "run_date": run_date.isoformat(),
        "mode": mode,
        "inputs": input_payload,
        "input_exact_duplicates": _exact_duplicates(manifests),
        "datasets": dataset_payload,
        "report_outputs": report_payload,
        "file_outputs": file_output_payload,
        "extra": extra or {},
    }
    return payload
