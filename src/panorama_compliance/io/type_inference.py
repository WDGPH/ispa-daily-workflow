from __future__ import annotations

import csv
import zipfile
from datetime import datetime
from pathlib import Path

from panorama_compliance.models import FileManifest


SUPPORTED_FORMATS = {".csv", ".tsv", ".json", ".xlsx", ".xls"}


def _read_text_sample(path: Path, byte_count: int = 4096) -> str:
    try:
        with path.open("rb") as handle:
            raw = handle.read(byte_count)
        return raw.decode("utf-8", errors="ignore")
    except Exception:
        return ""


def _detect_text_format(sample: str) -> str | None:
    stripped = sample.lstrip()
    if stripped.startswith(("{", "[")):
        return ".json"
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",\t")
        return ".csv" if dialect.delimiter == "," else ".tsv"
    except Exception:
        return None


def _detect_excel_format(path: Path) -> str | None:
    if zipfile.is_zipfile(path):
        return ".xlsx"
    try:
        import xlrd

        xlrd.open_workbook(path)
        return ".xls"
    except Exception:
        return None


def detect_file_suffix(path: Path) -> str | None:
    text_format = _detect_text_format(_read_text_sample(path))
    if text_format:
        return text_format
    return _detect_excel_format(path)


def infer_file_types(
    paths: list[Path], fix_extensions: bool = False
) -> list[FileManifest]:
    manifests: list[FileManifest] = []

    for path in paths:
        original_suffix = path.suffix.lower()
        stat = path.stat()
        detected_suffix = detect_file_suffix(path)
        detected_format = detected_suffix.lstrip(".") if detected_suffix else None
        renamed_to: Path | None = None

        if fix_extensions and detected_suffix and original_suffix != detected_suffix:
            candidate = path.with_suffix(detected_suffix)
            if not candidate.exists():
                path.rename(candidate)
                renamed_to = candidate
                path = candidate

        manifests.append(
            FileManifest(
                path=path,
                original_suffix=original_suffix,
                detected_suffix=detected_suffix,
                detected_format=detected_format,
                renamed_to=renamed_to,
                size_bytes=stat.st_size,
                modified_time=datetime.fromtimestamp(stat.st_mtime),
                created_time=datetime.fromtimestamp(stat.st_ctime),
            )
        )

    return manifests
