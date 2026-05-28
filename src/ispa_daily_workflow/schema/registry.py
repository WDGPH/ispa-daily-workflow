from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from ispa_daily_workflow.schema.validation import (
    LoadedSchema,
    ValidationError,
    load_schema,
)

DATASET_REGISTRY_FILENAME = "datasets_v1.0.json"


@dataclass(frozen=True)
class DatasetRegistry:
    version: str
    datasets: dict[str, str]
    registry_path: Path
    schema_root: Path


def _registry_cache_key(schema_root: Path) -> tuple[str, str]:
    return (str(schema_root.resolve()), DATASET_REGISTRY_FILENAME)


@lru_cache(maxsize=16)
def _load_registry_cached(schema_root_resolved: str, filename: str) -> DatasetRegistry:
    schema_root = Path(schema_root_resolved)
    registry_path = schema_root / filename
    if not registry_path.exists():
        raise FileNotFoundError(f"Schema dataset registry not found: {registry_path}")

    with registry_path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)

    version = str(payload.get("version", "")).strip()
    if not version:
        raise ValidationError(f"Dataset registry missing version: {registry_path}")

    datasets_payload = payload.get("datasets")
    if not isinstance(datasets_payload, dict) or not datasets_payload:
        raise ValidationError(f"Dataset registry missing datasets map: {registry_path}")

    datasets: dict[str, str] = {}
    for dataset_id, schema_filename in datasets_payload.items():
        dataset_key = str(dataset_id).strip()
        schema_name = str(schema_filename).strip()
        if not dataset_key:
            raise ValidationError(
                f"Dataset registry contains blank dataset id: {registry_path}"
            )
        if not schema_name:
            raise ValidationError(
                f"Dataset registry contains blank schema filename for {dataset_key!r}: {registry_path}"
            )
        datasets[dataset_key] = schema_name

    return DatasetRegistry(
        version=version,
        datasets=datasets,
        registry_path=registry_path,
        schema_root=schema_root,
    )


def load_dataset_registry(schema_root: Path) -> DatasetRegistry:
    cache_key = _registry_cache_key(schema_root)
    return _load_registry_cached(*cache_key)


def resolve_schema_path(dataset_id: str, *, schema_root: Path) -> Path:
    registry = load_dataset_registry(schema_root)
    filename = registry.datasets.get(dataset_id)
    if filename is None:
        raise ValidationError(
            f"Unknown dataset_id {dataset_id!r}; available dataset ids: {sorted(registry.datasets)}"
        )
    path = registry.schema_root / filename
    if not path.exists():
        raise FileNotFoundError(
            f"Schema file mapped from dataset_id {dataset_id!r} is missing: {path}"
        )
    return path


def resolve_dataset_schema(dataset_id: str, *, schema_root: Path) -> LoadedSchema:
    schema_path = resolve_schema_path(dataset_id, schema_root=schema_root)
    return load_schema(schema_root, schema_path.name)
